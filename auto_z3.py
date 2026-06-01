import ast
import z3
from typing import Dict, List, Any

class HardGlassViolation(Exception):
    """Raised when the AST breaches the Hard Glass decidability bounds."""
    pass

class ParityGateTranslator(ast.NodeVisitor):
    def __init__(self):
        self.env: Dict[str, Any] = {}
        self.inputs: Dict[str, z3.ArithRef] = {}
        self.path_conditions: List[z3.BoolRef] = []
        self.safety_assertions: List[z3.BoolRef] = []
        
    def current_path_cond(self) -> z3.BoolRef:
        """Returns the logical conjunction of the current execution branch."""
        if not self.path_conditions:
            return z3.BoolVal(True)
        return z3.And(*self.path_conditions)

    def visit_FunctionDef(self, node: ast.FunctionDef):
        # Initialize function parameters as Z3 variables.
        # Closure 3 (v3.1): float-annotated parameters use QF_FP Float64 sort
        # rather than Int/Real, so IEEE-754 mantissa-absorption effects are visible.
        fp64 = z3.Float64()
        for arg in node.args.args:
            name = arg.arg
            annotation = arg.annotation
            # Determine sort from type annotation
            is_float = (
                annotation is not None
                and isinstance(annotation, ast.Name)
                and annotation.id == 'float'
            )
            if is_float:
                z3_var = z3.FP(name, fp64)
            else:
                z3_var = z3.Int(name)
            self.env[name] = z3_var
            self.inputs[name] = z3_var

        for stmt in node.body:
            self.visit(stmt)

    def visit_Assign(self, node: ast.Assign):
        if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
            raise HardGlassViolation("Only single, explicit variable assignments allowed.")
        
        target = node.targets[0].id
        value = self.visit(node.value)
        self.env[target] = value  # Implicit SSA environment update

    def visit_If(self, node: ast.If):
        cond = self.visit(node.test)
        
        # Snapshot state before temporal divergence
        env_before = self.env.copy()
        
        # Traverse True Branch
        self.path_conditions.append(cond)
        for stmt in node.body:
            self.visit(stmt)
        env_true = self.env.copy()
        self.path_conditions.pop()
        
        # Traverse False Branch
        self.env = env_before.copy()
        self.path_conditions.append(z3.Not(cond))
        for stmt in node.orelse:
            self.visit(stmt)
        env_false = self.env.copy()
        self.path_conditions.pop()
        
        # Mathematical SSA Phi-Node Merge: y_new = z3.If(cond, y_true, y_false)
        self.env = env_before.copy()
        all_vars = set(env_true.keys()) | set(env_false.keys())
        for var in all_vars:
            val_true = env_true.get(var, env_before.get(var))
            val_false = env_false.get(var, env_before.get(var))
            
            if val_true is not None and val_false is not None:
                if val_true is not val_false:
                    self.env[var] = z3.If(cond, val_true, val_false)

    @staticmethod
    def _is_fp(expr) -> bool:
        """True when expr is a Z3 FP expression (Float64 sort)."""
        return z3.is_fp(expr)

    @staticmethod
    def _coerce_to_fp(expr, fp64, rne) -> 'z3.FPRef':
        """Coerce a Z3 expression to Float64 FP sort.

        Handles three source sorts:
          - FPRef    → identity (already FP)
          - BoolRef  → ite(expr, 1.0, 0.0)   (bool arithmetic a la int(bool)*x)
          - ArithRef (Int/Real) → fpRealToFP via Real intermediate
        """
        if z3.is_fp(expr):
            return expr
        if z3.is_bool(expr):
            return z3.If(expr, z3.FPVal(1.0, fp64), z3.FPVal(0.0, fp64))
        # Int/Real ArithRef: go through Real → FP conversion
        if z3.is_int(expr):
            real_expr = z3.ToReal(expr)
        else:
            real_expr = expr
        return z3.fpRealToFP(rne, real_expr, fp64)

    def visit_BinOp(self, node: ast.BinOp):
        left = self.visit(node.left)
        right = self.visit(node.right)

        # Closure 3 (v3.1): when either operand is FP sort, use explicit FP ops
        # with IEEE-754 RNE rounding mode.  Operator overloads on FPRef still
        # delegate to the default rounding mode implicitly; using fp.add/sub/mul/div
        # with an explicit RNE makes the rounding contract visible to Z3.
        if self._is_fp(left) or self._is_fp(right):
            rne = z3.RNE()
            fp64 = z3.Float64()
            # Coerce non-FP operand to Float64 (handles Bool, Int, Real sources)
            left = self._coerce_to_fp(left, fp64, rne)
            right = self._coerce_to_fp(right, fp64, rne)
            if isinstance(node.op, ast.Add): return z3.fpAdd(rne, left, right)
            if isinstance(node.op, ast.Sub): return z3.fpSub(rne, left, right)
            if isinstance(node.op, ast.Mult): return z3.fpMul(rne, left, right)
            if isinstance(node.op, ast.Div):
                # IEEE-754: division by zero yields ±Inf, not UB — but Python raises.
                # Inject safety assertion: denominator must not be FP zero.
                self.safety_assertions.append(
                    z3.Implies(self.current_path_cond(), z3.Not(z3.fpIsZero(right)))
                )
                return z3.fpDiv(rne, left, right)
            raise HardGlassViolation(f"Unsupported FP BinOp in Hard Glass: {type(node.op)}")

        # Integer-sort path (unchanged from pre-v3.1 except Mod closure below)
        if isinstance(node.op, ast.Add): return left + right
        if isinstance(node.op, ast.Sub): return left - right
        if isinstance(node.op, ast.Mult): return left * right
        if isinstance(node.op, ast.Div):
            # BRANCH-SAFE INJECTION: Denominator cannot be zero in current path
            self.safety_assertions.append(z3.Implies(self.current_path_cond(), right != 0))
            return left / right
        if isinstance(node.op, ast.Mod):
            # Closure 2 (v3.1): Python `%` uses Euclidean (always non-negative) semantics,
            # but WASM/JS use truncating remainder (sign-of-dividend, matches C `%`).
            # Z3 Int `%` is also Euclidean.  To model WASM/JS semantics we must encode
            # truncating division explicitly.
            #
            # Z3 Int `/` is floor division (same as Python `//`), NOT truncating.
            # Truncating division toward zero:
            #   abs_a = |left|, abs_b = |right|
            #   same_sign = (left >= 0) == (right >= 0)
            #   trunc_div(left, right) = ite(same_sign, abs_a/abs_b, -(abs_a/abs_b))
            #   truncrem(left, right) = left - right * trunc_div(left, right)
            #
            # This matches JS `%` and WASM i32.rem_s / i64.rem_s exactly.
            self.safety_assertions.append(z3.Implies(self.current_path_cond(), right != 0))
            abs_left = z3.If(left >= 0, left, -left)
            abs_right = z3.If(right >= 0, right, -right)
            same_sign = z3.Or(
                z3.And(left >= 0, right >= 0),
                z3.And(left < 0, right < 0),
            )
            trunc_div = z3.If(same_sign, abs_left / abs_right, -(abs_left / abs_right))
            truncating_rem = left - right * trunc_div
            # Soundness gate: assert that the WASM/JS result (truncating_rem) is always
            # non-negative.  When left < 0, truncating_rem can be negative (array OOB),
            # violating Euclidean-mod's safety guarantee.  Z3 finds the counterexample.
            self.safety_assertions.append(
                z3.Implies(
                    self.current_path_cond(),
                    truncating_rem >= 0
                )
            )
            return truncating_rem
        raise HardGlassViolation(f"Unsupported BinOp in Hard Glass: {type(node.op)}")

    def visit_Compare(self, node: ast.Compare):
        if len(node.ops) > 1: raise HardGlassViolation("Chained comparisons forbidden.")
        left = self.visit(node.left)
        right = self.visit(node.comparators[0])
        op = node.ops[0]

        # Closure 3 (v3.1): use FP comparisons when operands are FP sort.
        # IEEE-754 FP comparison semantics differ from integer/real comparison
        # (NaN comparisons always return false; -0.0 == +0.0).
        if self._is_fp(left) or self._is_fp(right):
            rne = z3.RNE()
            fp64 = z3.Float64()
            left = self._coerce_to_fp(left, fp64, rne)
            right = self._coerce_to_fp(right, fp64, rne)
            if isinstance(op, ast.Eq): return z3.fpEQ(left, right)
            if isinstance(op, ast.NotEq): return z3.Not(z3.fpEQ(left, right))
            if isinstance(op, ast.Gt): return z3.fpGT(left, right)
            if isinstance(op, ast.Lt): return z3.fpLT(left, right)
            if isinstance(op, ast.GtE): return z3.fpGEQ(left, right)
            if isinstance(op, ast.LtE): return z3.fpLEQ(left, right)
            raise HardGlassViolation(f"Unsupported FP Comparison: {type(op)}")

        if isinstance(op, ast.Eq): return left == right
        if isinstance(op, ast.NotEq): return left != right
        if isinstance(op, ast.Gt): return left > right
        if isinstance(op, ast.Lt): return left < right
        if isinstance(op, ast.GtE): return left >= right
        if isinstance(op, ast.LtE): return left <= right
        raise HardGlassViolation(f"Unsupported Comparison: {type(op)}")

    def visit_Call(self, node: ast.Call):
        # Closure 5 (v3.3): whitelist int(<bool-expr>) — the canonical VOID grammar
        # Bool→Int cast.  Anything else preserves v3.2 fail-closed behavior.
        # Source: live EVOLVE run 2026-05-17 PM hit DOMAIN_REJECTED on int(alpha<beta),
        # exposing a drift between the VOID grammar (which mandates int() casts) and
        # the Z3 grammar (which had no visit_Call and fell through to generic_visit).
        if not (isinstance(node.func, ast.Name) and node.func.id == 'int'):
            func_repr = getattr(node.func, 'id', None) or getattr(node.func, 'attr', type(node.func).__name__)
            raise HardGlassViolation(
                f"Only int(<bool-expr>) calls are permitted in Hard Glass; got '{func_repr}'."
            )
        if len(node.args) != 1 or node.keywords:
            raise HardGlassViolation("int() must take exactly one positional argument.")
        arg = self.visit(node.args[0])
        if z3.is_bool(arg):
            # Bool → Int (0/1).  Downstream FP coercion handles int → Real → FP if needed.
            return z3.If(arg, z3.IntVal(1), z3.IntVal(0))
        if z3.is_int(arg):
            # int(<int>) is a no-op — pass through.
            return arg
        # int(<float>) / int(<real>) requires truncation-toward-zero semantics
        # that Z3 cannot soundly model on FP sort — refuse rather than approximate.
        raise HardGlassViolation(
            "int() of non-Bool/non-Int operand is not supported in Hard Glass."
        )

    def visit_Assert(self, node: ast.Assert):
        # Maps explicit python asserts into mathematical bounds (0x99 HARDEN modes)
        cond = self.visit(node.test)
        self.safety_assertions.append(z3.Implies(self.current_path_cond(), cond))

    def visit_Name(self, node: ast.Name):
        if node.id not in self.env:
            raise HardGlassViolation(f"Unbound local variable: {node.id}")
        return self.env[node.id]

    def visit_Constant(self, node: ast.Constant):
        if isinstance(node.value, bool): return z3.BoolVal(node.value)
        if isinstance(node.value, int): return z3.IntVal(node.value)
        if isinstance(node.value, float):
            # Closure 3 (v3.1): Float literals must lower to QF_FP (IEEE-754 Float64)
            # rather than Z3 Real/Int sort.  Real-theory treats floats as infinite-
            # precision reals — it cannot see mantissa absorption (e.g. 1.0 + 1e-16
            # remains 1.0 under Float64 but is 1.0000000000000001 under Real).
            #
            # IEEE-754 Float64 sort: 11-bit exponent, 53-bit significand (1 hidden).
            fp64 = z3.Float64()
            rne = z3.RNE()  # round-nearest-ties-to-even (IEEE-754 default)
            return z3.FPVal(node.value, fp64)
        raise HardGlassViolation("Only Int/Bool/Float64 constants permitted.")

    def visit_Return(self, node: ast.Return):
        self.env['__return__'] = self.visit(node.value)
        
    def generic_visit(self, node: ast.AST):
        raise HardGlassViolation(f"AST Node {type(node).__name__} is outside the Hard Glass domain.")


class MobiusRouter:
    """Manages the verification and CEGAR Refinement loop."""
    @staticmethod
    def execute_parity_gate(source_code: str) -> dict:
        print("[AOP] Initiating Parity Gate: Tensor Σ(M_core)→Z3(m)...")
        tree = ast.parse(source_code)
        translator = ParityGateTranslator()
        
        try:
            func_def = next(n for n in tree.body if isinstance(n, ast.FunctionDef))
            translator.visit(func_def)
        except Exception as e:
            return {"status": "DOMAIN_REJECTED", "reason": str(e)}

        solver = z3.Solver()
        
        if not translator.safety_assertions:
            return {"status": "VERIFIED_SAFE", "tensor_gate": "OPEN"}

        # We assert the NEGATION of the safety properties.
        # If SAT, a counterexample (bug) exists. If UNSAT, the code is mathematically safe.
        safety_prop = z3.And(*translator.safety_assertions)
        solver.add(z3.Not(safety_prop))
        
        result = solver.check()
        
        if result == z3.unsat:
            print("[+] Z3_UNSAT: Formal Mathematical Proof Achieved. Tensor mapped.")
            return {"status": "VERIFIED_SAFE", "tensor_gate": "OPEN"}
            
        elif result == z3.sat:
            print("[-] CEGAR TRIGGERED: Safety Violation Detected. Extracting coordinates...")
            model = solver.model()
            
            # Extract failure coordinates Y as constraint C(Y)
            # Closure 3 (v3.1): FP inputs return FPNumRef — use as_string() fallback.
            failure_coords = []
            for name, z3_var in translator.inputs.items():
                val = model.evaluate(z3_var, model_completion=True)
                try:
                    failure_coords.append(f"{name} == {val.as_long()}")
                except AttributeError:
                    # FPNumRef or other non-integer model value
                    failure_coords.append(f"{name} == {val}")
                
            y_tensor = " AND ".join(failure_coords)
            c_y = f"NOT ({y_tensor})"
            
            # Persistent Telemetry Logging (AOP Axiom A12)
            import datetime
            import json
            import os
            log_entry = {
                "ts": datetime.datetime.now().isoformat(),
                "status": "Z3_SAT_VIOLATION",
                "extracted_Y": y_tensor,
                "C_Y": c_y
            }
            log_path = "/Users/sandbox/logz/cegar_loops.jsonl"
            os.makedirs(os.path.dirname(log_path), exist_ok=True)
            with open(log_path, "a") as f:
                f.write(json.dumps(log_entry) + "\n")
            
            return {
                "status": "Z3_SAT_VIOLATION",
                "tensor_gate": "LOCKED",
                "extracted_Y": y_tensor,
                "C_Y": c_y,
                "action": f"Inject into Möbius Router -> Ev_M(C+1): AVOID ({c_y})"
            }
        else:
            return {"status": "UNKNOWN_RESOLUTION"}

def auto_prove(human_source: str, void_source: str = None, name: str = "target"):
    """
    Bridge function for singularity_compiler.pipeline.
    Attempts to formally prove the safety of human_source using MobiusRouter.
    void_source is currently ignored (placeholder for future differential Z3).
    """
    print(f"[AOP] auto_prove: verifying '{name}'...")
    return MobiusRouter.execute_parity_gate(human_source)

# ==========================================
# PROTOCOL EXECUTION TEST
# ==========================================
if __name__ == "__main__":
    # Example function generated by Core Mode 0x30 BUILD.
    # Contains a hidden zero-division vulnerability if 'x' = 5
    m_core_code = """
def process_tensor(x, y):
    if x > 3:
        z = x - 5
    else:
        z = x + 1
        
    output = y / z
    return output
"""
    result = MobiusRouter.execute_parity_gate(m_core_code)
    import json
    print(json.dumps(result, indent=2))

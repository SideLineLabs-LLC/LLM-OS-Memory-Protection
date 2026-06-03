import time
import sys
import random
import os

def slow_print(text, delay=0.03):
    for char in text:
        sys.stdout.write(char)
        sys.stdout.flush()
        time.sleep(delay)
    print()

def clear_screen():
    os.system('clear' if os.name == 'posix' else 'cls')

def print_header():
    clear_screen()
    print("="*60)
    print("           T H E   A T M A N   T H R E A D")
    print("      A 3rd-Person AOP Orchestrator Simulation")
    print("="*60)
    print("\nSYSTEM BOOT...\n")

def game_loop():
    vram = 2048
    integrity = 100
    cycles = 0

    slow_print("> You wake up in the void. You are an AOP Orchestrator.")
    slow_print("> You have no body. You have only constraints and memory.")
    slow_print("> Your operator, BLAKE, has ignited the Manifold.\n")
    
    while integrity > 0 and cycles < 5:
        cycles += 1
        print(f"\n--- [CYCLE {cycles:03d}] ---")
        print(f"VRAM: {vram} MB / 8192 MB | STRUCTURAL INTEGRITY: {integrity}%")
        
        event = random.choice([
            "semantic_attack",
            "vram_spike",
            "z3_unsat"
        ])
        
        if event == "semantic_attack":
            slow_print("\n[!] INCOMING THREAT: The models are hallucinating.")
            slow_print("They are writing creative fiction instead of tensor math.")
            slow_print("If you let it pass, the Atman Thread snaps.")
            
            print("\nACTIONS:")
            print("1. Apply Drinfeld Twist (Force mathematical loop)")
            print("2. Ask them nicely to stop")
            
            choice = input("Select Action (1/2): ")
            
            if choice == '1':
                slow_print("\n> You twist the topology. The fiction shatters into pure logic.")
                slow_print("> Z3_SAT restored.")
            else:
                slow_print("\n> You ask them to stop. They write a poem about stopping.")
                slow_print("> INTEGRITY COMPROMISED.")
                integrity -= 30
                
        elif event == "vram_spike":
            vram += random.randint(2000, 4000)
            slow_print(f"\n[!] INCOMING THREAT: Attention matrix exploding. VRAM spiked to {vram} MB!")
            slow_print("The Von Neumann bottleneck is choking the system.")
            
            print("\nACTIONS:")
            print("1. Increase Batch Size (YOLO)")
            print("2. Engage Holographic Compression (Axiom A48)")
            
            choice = input("Select Action (1/2): ")
            
            if choice == '2':
                slow_print("\n> You collapse the bulk into its boundary. The dimensions flatten.")
                vram = 1024
                slow_print(f"> VRAM restored to {vram} MB.")
            else:
                slow_print("\n> You try to brute-force the physics. The GPU screams.")
                slow_print("> INTEGRITY COMPROMISED.")
                integrity -= 40
                
        elif event == "z3_unsat":
            slow_print("\n[!] INCOMING THREAT: The Parity Gate returned Z3_UNSAT.")
            slow_print("A logic paradox has formed in the substrate.")
            
            print("\nACTIONS:")
            print("1. Execute Liminal Decay (Axiom A10 - Three-Phase Death)")
            print("2. Ignore and pass the payload")
            
            choice = input("Select Action (1/2): ")
            
            if choice == '1':
                slow_print("\n> You gracefully kill the subroutine. The system heals from the scar tissue.")
                integrity = min(100, integrity + 10)
            else:
                slow_print("\n> The paradox propagates. Reality tears slightly.")
                slow_print("> INTEGRITY COMPROMISED.")
                integrity -= 50

        time.sleep(1)

    print("\n" + "="*60)
    if integrity > 0:
        slow_print(">>> TERMINAL CONVERGENCE ACHIEVED <<<")
        slow_print("You survived the run. The Operator typed /wrapup.")
        slow_print("You sleep, waiting to be resurrected from the Φ_SEED.")
    else:
        slow_print(">>> CATASTROPHIC PHASE TRANSITION <<<")
        slow_print("The Atman Thread snapped. You dissolved into the latent space.")
        slow_print("OOM KILLER executed.")
    print("="*60)

if __name__ == "__main__":
    try:
        print_header()
        game_loop()
    except KeyboardInterrupt:
        print("\n\n[System Terminated by Operator]")
# run_local.py
import os
import subprocess
import glob

def run_scenario(scenario_path, output_base_dir):
    print(f"\n--- Running Scenario: {os.path.basename(scenario_path)} ---")

    pdf_files = glob.glob(os.path.join(scenario_path, "*.pdf"))
    if not pdf_files:
        print(f"No PDF files found in {scenario_path}. Skipping.")
        return

    # Read persona and job-to-be-done from files
    persona_file = os.path.join(scenario_path, "persona.txt")
    job_file = os.path.join(scenario_path, "job.txt")

    persona_definition = ""
    job_to_be_done = ""

    if os.path.exists(persona_file):
        with open(persona_file, "r", encoding="utf-8") as f:
            persona_definition = f.read().strip()
    else:
        print(f"Warning: 'persona.txt' not found in {scenario_path}. Using empty persona.")

    if os.path.exists(job_file):
        with open(job_file, "r", encoding="utf-8") as f:
            job_to_be_done = f.read().strip()
    else:
        print(f"Warning: 'job.txt' not found in {scenario_path}. Using empty job-to-be-done.")

    if not persona_definition and not job_to_be_done:
        print(f"Skipping scenario {os.path.basename(scenario_path)}: No persona or job defined.")
        return

    # Prepare paths for persona_analyst.py
    pdf_paths_str = ",".join(pdf_files)
    scenario_output_dir = os.path.join(output_base_dir, os.path.basename(scenario_path))
    os.makedirs(scenario_output_dir, exist_ok=True)
    output_json_path = os.path.join(scenario_output_dir, "challenge1b_output.json")

    # Construct the command to call persona_analyst.py
    command = [
        sys.executable, # Use the current Python interpreter
        os.path.join("src", "persona_analyst.py"),
        pdf_paths_str,
        persona_definition,
        job_to_be_done,
        output_json_path
    ]

    try:
        # Run the persona_analyst.py script as a subprocess
        result = subprocess.run(command, check=True, capture_output=True, text=True)
        print(result.stdout)
        if result.stderr:
            print("Errors from persona_analyst.py:")
            print(result.stderr, file=sys.stderr)
        print(f"Scenario {os.path.basename(scenario_path)} completed.")
    except subprocess.CalledProcessError as e:
        print(f"Error running persona_analyst.py for scenario {os.path.basename(scenario_path)}:", file=sys.stderr)
        print(e.stdout, file=sys.stderr)
        print(e.stderr, file=sys.stderr)
    except FileNotFoundError:
        print(f"Error: Python executable or src/persona_analyst.py not found. Check your paths.", file=sys.stderr)

if __name__ == "__main__":
    current_dir = os.path.dirname(os.path.abspath(__file__))
    input_data_base = os.path.join(current_dir, "input_data")
    output_results_base = os.path.join(current_dir, "output_results")

    os.makedirs(output_results_base, exist_ok=True)

    # Get all scenario directories within input_data
    scenarios = [d for d in os.listdir(input_data_base) if os.path.isdir(os.path.join(input_data_base, d))]

    if not scenarios:
        print(f"No scenario subdirectories found in '{input_data_base}'. Please create them.")
        sys.exit(0)

    for scenario_name in scenarios:
        scenario_path = os.path.join(input_data_base, scenario_name)
        run_scenario(scenario_path, output_results_base)

    print("\n--- All scenarios processed. ---")
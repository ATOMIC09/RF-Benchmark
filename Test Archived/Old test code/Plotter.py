import json
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import sys
import os

# --- Configuration ---
INPUT_FILE = 'rf433_results.json'

# Set font to Niramit
plt.rcParams['font.family'] = 'Niramit'

def load_results(filename):
    """Loads test results from JSON file."""
    if not os.path.exists(filename):
        print(f"Error: {filename} not found!")
        print("Please run Receiver.py first to generate test data.")
        sys.exit(1)

    with open(filename, 'r') as f:
        return json.load(f)

def create_mtu_window(mtu_size):
    """Creates a new figure window for a specific MTU size."""
    fig, ax1 = plt.subplots(figsize=(10, 6))
    ax2 = ax1.twinx()
    fig.canvas.manager.set_window_title(f'RF433 Performance - MTU {mtu_size} Bytes')
    return fig, ax1, ax2

def plot_mtu_data(fig, ax1, ax2, mtu_size, tests):
    """Plots throughput and packet loss for a specific MTU size."""
    if not tests:
        return

    # Sort by air gap
    tests_sorted = sorted(tests, key=lambda x: x['gap_ms'])
    gaps = [t['gap_ms'] for t in tests_sorted]

    # Handle both old and new JSON formats
    if 'rf_throughput' in tests_sorted[0]:
        rf_throughputs = [t['rf_throughput'] for t in tests_sorted]
        expected_throughputs = [t['expected_throughput'] for t in tests_sorted]
    else:
        # Old format compatibility
        rf_throughputs = [t['throughput'] for t in tests_sorted]
        expected_throughputs = None

    losses = [t['loss'] for t in tests_sorted]

    # Extract packet info if available
    packets_info = []
    for t in tests_sorted:
        if 'packets_received' in t and 'packets_expected' in t:
            packets_info.append(f"{t['packets_received']}/{t['packets_expected']}")
        else:
            packets_info.append("")

    # Plot throughput and packet loss
    ax1.plot(gaps, rf_throughputs, 'b-o', linewidth=2, markersize=8, label='RF Speed')
    ax2.plot(gaps, losses, 'r-x', linewidth=2, markersize=8, label='Packet Loss')

    # Add data labels for RF throughput
    for i, (gap, throughput) in enumerate(zip(gaps, rf_throughputs)):
        ax1.annotate(f'{throughput:.0f}',
                    xy=(gap, throughput),
                    xytext=(0, 10),
                    textcoords='offset points',
                    ha='center',
                    fontsize=8,
                    color='blue',
                    weight='bold')

    # Add data labels for packet loss
    for i, (gap, loss) in enumerate(zip(gaps, losses)):
        label_text = f'{loss:.1f}%'
        if packets_info[i]:
            label_text = f'{loss:.1f}%\n({packets_info[i]})'

        ax2.annotate(label_text,
                    xy=(gap, loss),
                    xytext=(0, -25),
                    textcoords='offset points',
                    ha='center',
                    fontsize=8,
                    color='red',
                    weight='bold')

    # Formatting
    ax1.set_xlabel('Air Gap (ms)', fontsize=11, fontweight='bold')
    ax1.set_ylabel('Throughput (Bytes/sec)', color='b', fontsize=11, fontweight='bold')
    ax2.set_ylabel('Packet Loss (%)', color='r', fontsize=11, fontweight='bold')
    ax2.set_ylim(-5, 105)

    ax1.grid(True, linestyle='--', alpha=0.6)
    ax1.set_title(f'MTU {mtu_size} Bytes - RF433 Performance', fontweight='bold', fontsize=13)

    # Color the tick labels
    ax1.tick_params(axis='y', labelcolor='b', labelsize=10)
    ax2.tick_params(axis='y', labelcolor='r', labelsize=10)
    ax1.tick_params(axis='x', labelsize=10)

    # Add legends with better positioning
    ax1.legend(loc='upper left', fontsize=9)
    ax2.legend(loc='upper right', fontsize=9)

    fig.tight_layout()

def main():
    # Load data from JSON
    print(f"Loading results from {INPUT_FILE}...")
    data_by_mtu = load_results(INPUT_FILE)

    if not data_by_mtu:
        print("No test data found in file!")
        sys.exit(1)

    print(f"Found data for {len(data_by_mtu)} MTU sizes.")

    # Create a separate window for each MTU
    for mtu_size_str in sorted(data_by_mtu.keys(), key=lambda x: int(x)):
        mtu_size = int(mtu_size_str)
        tests = data_by_mtu[mtu_size_str]

        print(f"  Plotting MTU {mtu_size} bytes ({len(tests)} tests)")

        fig, ax1, ax2 = create_mtu_window(mtu_size)
        plot_mtu_data(fig, ax1, ax2, mtu_size, tests)

    print("\nAll charts created. Close all windows to exit.")
    plt.show()

if __name__ == '__main__':
    main()

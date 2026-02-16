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

def plot_overview(data_by_mtu):
    """Creates overview charts showing all MTU sizes together."""

    # Create figure with 2 subplots side by side
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 6))
    fig.canvas.manager.set_window_title('RF433 Performance Overview - All MTU Sizes')

    # Define colors for each MTU size
    colors = plt.cm.viridis(range(0, 256, 256 // len(data_by_mtu)))

    # Plot 1: Throughput vs MTU Size (grouped by air gap)
    air_gaps_set = set()
    for mtu_data in data_by_mtu.values():
        for test in mtu_data:
            air_gaps_set.add(test['gap_ms'])

    air_gaps = sorted(list(air_gaps_set))

    # Group data by air gap
    for gap in air_gaps:
        mtus = []
        throughputs = []

        for mtu_str in sorted(data_by_mtu.keys(), key=lambda x: int(x)):
            mtu = int(mtu_str)
            # Find test with this air gap
            for test in data_by_mtu[mtu_str]:
                if test['gap_ms'] == gap:
                    mtus.append(mtu)
                    throughputs.append(test['rf_throughput'])
                    break

        ax1.plot(mtus, throughputs, '-o', linewidth=2, markersize=6, label=f'{gap}ms gap')

    ax1.set_xlabel('MTU Size (bytes)', fontsize=11, fontweight='bold')
    ax1.set_ylabel('RF Throughput (Bytes/sec)', fontsize=11, fontweight='bold')
    ax1.set_title('Throughput vs MTU Size', fontweight='bold', fontsize=13)
    ax1.grid(True, linestyle='--', alpha=0.6)
    ax1.legend(loc='best', fontsize=9)

    # Plot 2: Packet Loss vs MTU Size (grouped by air gap)
    for gap in air_gaps:
        mtus = []
        losses = []

        for mtu_str in sorted(data_by_mtu.keys(), key=lambda x: int(x)):
            mtu = int(mtu_str)
            # Find test with this air gap
            for test in data_by_mtu[mtu_str]:
                if test['gap_ms'] == gap:
                    mtus.append(mtu)
                    losses.append(test['loss'])
                    break

        ax2.plot(mtus, losses, '-o', linewidth=2, markersize=6, label=f'{gap}ms gap')

    ax2.set_xlabel('MTU Size (bytes)', fontsize=11, fontweight='bold')
    ax2.set_ylabel('Packet Loss (%)', fontsize=11, fontweight='bold')
    ax2.set_title('Packet Loss vs MTU Size', fontweight='bold', fontsize=13)
    ax2.set_ylim(-2, max(10, max([test['loss'] for tests in data_by_mtu.values() for test in tests]) + 2))
    ax2.grid(True, linestyle='--', alpha=0.6)
    ax2.legend(loc='best', fontsize=9)

    fig.tight_layout()

def plot_heatmap(data_by_mtu):
    """Creates heatmap showing throughput across MTU sizes and air gaps."""

    # Get all unique MTU sizes and air gaps
    mtus = sorted([int(k) for k in data_by_mtu.keys()])

    air_gaps_set = set()
    for mtu_data in data_by_mtu.values():
        for test in mtu_data:
            air_gaps_set.add(test['gap_ms'])
    air_gaps = sorted(list(air_gaps_set))

    # Create matrix for heatmap
    throughput_matrix = []
    loss_matrix = []

    for gap in air_gaps:
        throughput_row = []
        loss_row = []
        for mtu in mtus:
            mtu_str = str(mtu)
            # Find test with this air gap
            found = False
            for test in data_by_mtu[mtu_str]:
                if test['gap_ms'] == gap:
                    throughput_row.append(test['rf_throughput'])
                    loss_row.append(test['loss'])
                    found = True
                    break
            if not found:
                throughput_row.append(0)
                loss_row.append(0)

        throughput_matrix.append(throughput_row)
        loss_matrix.append(loss_row)

    # Create heatmap figure
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 6))
    fig.canvas.manager.set_window_title('RF433 Performance Heatmap')

    # Throughput heatmap
    im1 = ax1.imshow(throughput_matrix, cmap='YlGn', aspect='auto')
    ax1.set_xticks(range(len(mtus)))
    ax1.set_xticklabels(mtus)
    ax1.set_yticks(range(len(air_gaps)))
    ax1.set_yticklabels([f'{g}ms' for g in air_gaps])
    ax1.set_xlabel('MTU Size (bytes)', fontsize=11, fontweight='bold')
    ax1.set_ylabel('Air Gap', fontsize=11, fontweight='bold')
    ax1.set_title('RF Throughput Heatmap (B/s)', fontweight='bold', fontsize=13)

    # Add colorbar
    cbar1 = plt.colorbar(im1, ax=ax1)
    cbar1.set_label('Throughput (B/s)', fontsize=10)

    # Add text annotations
    for i in range(len(air_gaps)):
        for j in range(len(mtus)):
            text = ax1.text(j, i, f'{throughput_matrix[i][j]:.0f}',
                          ha="center", va="center", color="black", fontsize=8)

    # Packet loss heatmap
    im2 = ax2.imshow(loss_matrix, cmap='Reds', aspect='auto')
    ax2.set_xticks(range(len(mtus)))
    ax2.set_xticklabels(mtus)
    ax2.set_yticks(range(len(air_gaps)))
    ax2.set_yticklabels([f'{g}ms' for g in air_gaps])
    ax2.set_xlabel('MTU Size (bytes)', fontsize=11, fontweight='bold')
    ax2.set_ylabel('Air Gap', fontsize=11, fontweight='bold')
    ax2.set_title('Packet Loss Heatmap (%)', fontweight='bold', fontsize=13)

    # Add colorbar
    cbar2 = plt.colorbar(im2, ax=ax2)
    cbar2.set_label('Loss (%)', fontsize=10)

    # Add text annotations
    for i in range(len(air_gaps)):
        for j in range(len(mtus)):
            text = ax2.text(j, i, f'{loss_matrix[i][j]:.1f}%',
                          ha="center", va="center", color="black", fontsize=8)

    fig.tight_layout()

def main():
    # Load data from JSON
    print(f"Loading results from {INPUT_FILE}...")
    data_by_mtu = load_results(INPUT_FILE)

    if not data_by_mtu:
        print("No test data found in file!")
        sys.exit(1)

    print(f"Found data for {len(data_by_mtu)} MTU sizes.")
    print("Creating overview charts...")

    # Create overview line charts
    plot_overview(data_by_mtu)

    # Create heatmap
    plot_heatmap(data_by_mtu)

    print("\nOverview charts created. Close all windows to exit.")
    plt.show()

if __name__ == '__main__':
    main()

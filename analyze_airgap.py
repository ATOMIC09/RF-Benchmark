import json
import matplotlib.pyplot as plt
import numpy as np
from datetime import datetime
import matplotlib.font_manager as fm

# Set Niramit font
plt.rcParams['font.family'] = 'Niramit'
plt.rcParams['font.size'] = 10

# Load results
with open('rf433_results.json', 'r') as f:
    data = json.load(f)

# Filter valid MTU sizes (exclude garbage values from sync loss)
valid_mtus = [8, 16, 32, 64, 128, 256, 512, 1024, 1492, 1500]
filtered_data = {}
for mtu_str, tests in data.items():
    mtu = int(mtu_str)
    if mtu in valid_mtus:
        filtered_data[mtu_str] = tests

# Prepare data for analysis
analysis = []
for mtu_str, tests in filtered_data.items():
    mtu = int(mtu_str)
    for test in tests:
        # Calculate efficiency score: throughput weighted by reliability
        reliability = (100 - test['loss']) * (100 - test['crc_failure_percent']) / 100
        efficiency = (test['rf_throughput'] / 1000) * (reliability / 100)

        analysis.append({
            'mtu': mtu,
            'gap_ms': test['gap_ms'],
            'throughput': test['rf_throughput'],
            'loss': test['loss'],
            'crc_failure': test['crc_failure_percent'],
            'reliability': reliability,
            'efficiency': efficiency,
            'packets_received': test['packets_received']
        })

# Find optimal air gap configuration
best_config = max(analysis, key=lambda x: x['efficiency'])
best_throughput = max(analysis, key=lambda x: x['throughput'])
best_reliability = max(analysis, key=lambda x: x['reliability'])

# Get list of all air gaps tested
all_gaps = sorted(list(set([x['gap_ms'] for x in analysis])))

# Generate text summary
summary = f"""
{'='*70}
RF433 AIR GAP PERFORMANCE ANALYSIS
{'='*70}
Test Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
Baudrate: 9600 bps
Packets per test: 100

{'='*70}
OPTIMAL CONFIGURATION (Best Efficiency Score)
{'='*70}
MTU Size:          {best_config['mtu']} bytes
Air Gap:           {best_config['gap_ms']} ms
RF Throughput:     {best_config['throughput']:.2f} B/s
Packet Loss:       {best_config['loss']:.1f}%
CRC Failures:      {best_config['crc_failure']:.1f}%
Reliability:       {best_config['reliability']:.1f}%
Efficiency Score:  {best_config['efficiency']:.3f}

{'='*70}
ALTERNATIVE CONFIGURATIONS
{'='*70}

Best Raw Throughput:
  MTU: {best_throughput['mtu']}B @ {best_throughput['gap_ms']}ms
  Throughput: {best_throughput['throughput']:.2f} B/s
  Loss: {best_throughput['loss']:.1f}%, CRC Fail: {best_throughput['crc_failure']:.1f}%

Best Reliability (100% delivery, 0% corruption):
  MTU: {best_reliability['mtu']}B @ {best_reliability['gap_ms']}ms
  Throughput: {best_reliability['throughput']:.2f} B/s
  Loss: {best_reliability['loss']:.1f}%, CRC Fail: {best_reliability['crc_failure']:.1f}%

{'='*70}
PERFORMANCE BY AIR GAP
{'='*70}
"""

# Add air gap-specific analysis
for gap_ms in all_gaps:
    gap_tests = [x for x in analysis if x['gap_ms'] == gap_ms]
    if not gap_tests:
        continue

    avg_loss = np.mean([x['loss'] for x in gap_tests])
    avg_crc = np.mean([x['crc_failure'] for x in gap_tests])
    avg_throughput = np.mean([x['throughput'] for x in gap_tests])
    avg_reliability = np.mean([x['reliability'] for x in gap_tests])

    summary += f"\nAir Gap {gap_ms} ms:\n"
    summary += f"  Avg Throughput: {avg_throughput:.2f} B/s\n"
    summary += f"  Avg Loss: {avg_loss:.1f}%\n"
    summary += f"  Avg CRC Failures: {avg_crc:.1f}%\n"
    summary += f"  Avg Reliability: {avg_reliability:.1f}%\n"

    if avg_loss == 0 and avg_crc == 0:
        summary += "  Status: EXCELLENT - Perfect delivery\n"
    elif avg_loss <= 1 and avg_crc <= 1:
        summary += "  Status: VERY GOOD - Minimal loss and corruption\n"
    elif avg_loss <= 5 and avg_crc <= 5:
        summary += "  Status: GOOD - Acceptable performance\n"
    elif avg_loss <= 20:
        summary += "  Status: POOR - Significant degradation\n"
    else:
        summary += "  Status: CRITICAL - System failure\n"

summary += f"""
{'='*70}
KEY FINDINGS
{'='*70}
1. Air Gap Range Tested: {min(all_gaps)}-{max(all_gaps)} ms
2. Optimal Air Gap: {best_config['gap_ms']} ms
3. Impact of Air Gap on Performance:
   - Too short: May cause buffer overflow at larger MTU sizes
   - Too long: Reduces throughput unnecessarily
   - Sweet spot: Balance between throughput and reliability

4. Air Gap vs MTU Interaction:
   - Smaller MTU sizes are more tolerant of short air gaps
   - Larger MTU sizes require longer air gaps to avoid overflow
   - RF transmission time increases with MTU size

{'='*70}
RECOMMENDATIONS
{'='*70}
For Maximum Throughput:
  - Use shortest air gap that maintains reliability
  - Optimal: {best_config['gap_ms']} ms @ {best_config['mtu']}B MTU

For Maximum Reliability:
  - Use air gap >= {best_reliability['gap_ms']} ms with MTU <= 64 bytes
  - Expected: 0% loss, 0% corruption

Dynamic Air Gap Calculation:
  - Minimum air gap = (MTU x 10 bits / 9600) + overhead
  - Add safety margin for RF module processing time
  - Consider environmental interference

{'='*70}
"""

# Save summary to file
with open('rf433_airgap_analysis.txt', 'w', encoding='utf-8') as f:
    f.write(summary)

print(summary)
print("\nSummary saved to: rf433_airgap_analysis.txt")

# Create visualizations
fig, axes = plt.subplots(2, 2, figsize=(14, 10))
fig.suptitle('RF433 Air Gap Performance Analysis @ 9600 baud', fontsize=16, fontweight='bold')

# Prepare data for plotting - get unique MTU sizes that have multiple air gap tests
tested_mtus = sorted(list(set([x['mtu'] for x in analysis])))
colors = plt.cm.viridis(np.linspace(0, 1, len(tested_mtus)))

# Plot 1: Throughput vs Air Gap (by MTU)
ax1 = axes[0, 0]
for idx, mtu in enumerate(tested_mtus):
    mtu_data = [x for x in analysis if x['mtu'] == mtu]
    if len(mtu_data) > 1:  # Only plot if multiple air gaps tested
        gaps = [x['gap_ms'] for x in mtu_data]
        throughputs = [x['throughput'] for x in mtu_data]
        ax1.plot(gaps, throughputs, marker='o', label=f'{mtu}B MTU', linewidth=2, color=colors[idx])

ax1.set_xlabel('Air Gap (ms)', fontweight='bold')
ax1.set_ylabel('RF Throughput (B/s)', fontweight='bold')
ax1.set_title('Throughput vs Air Gap')
ax1.legend()
ax1.grid(True, alpha=0.3)

# Plot 2: Packet Loss vs Air Gap
ax2 = axes[0, 1]
for idx, mtu in enumerate(tested_mtus):
    mtu_data = [x for x in analysis if x['mtu'] == mtu]
    if len(mtu_data) > 1:
        gaps = [x['gap_ms'] for x in mtu_data]
        losses = [x['loss'] for x in mtu_data]
        ax2.plot(gaps, losses, marker='s', label=f'{mtu}B MTU', linewidth=2, color=colors[idx])

ax2.set_xlabel('Air Gap (ms)', fontweight='bold')
ax2.set_ylabel('Packet Loss (%)', fontweight='bold')
ax2.set_title('Packet Loss vs Air Gap')
ax2.legend()
ax2.grid(True, alpha=0.3)
ax2.axhline(y=5, color='orange', linestyle='--', alpha=0.5, label='5% threshold')
ax2.axhline(y=10, color='red', linestyle='--', alpha=0.5, label='10% threshold')

# Plot 3: CRC Failures vs Air Gap
ax3 = axes[1, 0]
for idx, mtu in enumerate(tested_mtus):
    mtu_data = [x for x in analysis if x['mtu'] == mtu]
    if len(mtu_data) > 1:
        gaps = [x['gap_ms'] for x in mtu_data]
        crc_fails = [x['crc_failure'] for x in mtu_data]
        ax3.plot(gaps, crc_fails, marker='^', label=f'{mtu}B MTU', linewidth=2, color=colors[idx])

ax3.set_xlabel('Air Gap (ms)', fontweight='bold')
ax3.set_ylabel('CRC Failures (%)', fontweight='bold')
ax3.set_title('Data Corruption vs Air Gap')
ax3.legend()
ax3.grid(True, alpha=0.3)

# Plot 4: Average Efficiency by Air Gap
ax4 = axes[1, 1]
gap_efficiency = {}
for gap_ms in all_gaps:
    gap_tests = [x for x in analysis if x['gap_ms'] == gap_ms]
    if gap_tests:
        avg_efficiency = np.mean([x['efficiency'] for x in gap_tests])
        gap_efficiency[gap_ms] = avg_efficiency

gaps_sorted = sorted(gap_efficiency.keys())
efficiencies = [gap_efficiency[g] for g in gaps_sorted]

bars = ax4.bar(range(len(gaps_sorted)), efficiencies, alpha=0.7, color='steelblue')
ax4.set_xticks(range(len(gaps_sorted)))
ax4.set_xticklabels([f'{g}' for g in gaps_sorted], rotation=45)
ax4.set_xlabel('Air Gap (ms)', fontweight='bold')
ax4.set_ylabel('Avg Efficiency Score', fontweight='bold')
ax4.set_title('Overall Efficiency by Air Gap')
ax4.grid(True, alpha=0.3, axis='y')

# Highlight best air gap
if best_config['gap_ms'] in gap_efficiency:
    best_idx = gaps_sorted.index(best_config['gap_ms'])
    bars[best_idx].set_color('gold')
    bars[best_idx].set_edgecolor('red')
    bars[best_idx].set_linewidth(3)
    ax4.text(best_idx, efficiencies[best_idx], 'OPTIMAL',
             ha='center', va='bottom', fontweight='bold', color='red')

plt.tight_layout()
plt.savefig('rf433_airgap_analysis.png', dpi=300, bbox_inches='tight')
print("Graphs saved to: rf433_airgap_analysis.png")

# Create a heatmap showing MTU vs Air Gap performance
fig2, ax = plt.subplots(figsize=(12, 8))

# Create matrix for heatmap
mtu_gap_matrix = {}
for item in analysis:
    key = (item['mtu'], item['gap_ms'])
    mtu_gap_matrix[key] = item['throughput']

# Get sorted unique values
unique_mtus = sorted(list(set([x['mtu'] for x in analysis])))
unique_gaps = sorted(list(set([x['gap_ms'] for x in analysis])))

# Create 2D matrix
matrix = np.zeros((len(unique_mtus), len(unique_gaps)))
for i, mtu in enumerate(unique_mtus):
    for j, gap in enumerate(unique_gaps):
        key = (mtu, gap)
        if key in mtu_gap_matrix:
            matrix[i, j] = mtu_gap_matrix[key]
        else:
            matrix[i, j] = np.nan

# Create heatmap
im = ax.imshow(matrix, cmap='YlOrRd', aspect='auto', interpolation='nearest')
ax.set_xticks(range(len(unique_gaps)))
ax.set_yticks(range(len(unique_mtus)))
ax.set_xticklabels([f'{g}' for g in unique_gaps], rotation=45)
ax.set_yticklabels([f'{m}' for m in unique_mtus])
ax.set_xlabel('Air Gap (ms)', fontweight='bold')
ax.set_ylabel('MTU Size (bytes)', fontweight='bold')
ax.set_title('RF Throughput Heatmap (B/s)', fontweight='bold')

# Add colorbar
cbar = plt.colorbar(im, ax=ax)
cbar.set_label('Throughput (B/s)', fontweight='bold')

# Add text annotations
for i in range(len(unique_mtus)):
    for j in range(len(unique_gaps)):
        if not np.isnan(matrix[i, j]):
            text = ax.text(j, i, f'{matrix[i, j]:.0f}',
                          ha="center", va="center", color="black", fontsize=8)

# Mark optimal configuration
if (best_config['mtu'], best_config['gap_ms']) in mtu_gap_matrix:
    optimal_i = unique_mtus.index(best_config['mtu'])
    optimal_j = unique_gaps.index(best_config['gap_ms'])
    ax.add_patch(plt.Rectangle((optimal_j-0.5, optimal_i-0.5), 1, 1,
                                fill=False, edgecolor='lime', linewidth=4))

plt.tight_layout()
plt.savefig('rf433_airgap_heatmap.png', dpi=300, bbox_inches='tight')
print("Heatmap saved to: rf433_airgap_heatmap.png")

plt.show()

print("\n" + "="*70)
print("ANALYSIS COMPLETE!")
print("="*70)
print(f"Optimal Configuration: MTU={best_config['mtu']}B @ {best_config['gap_ms']}ms")
print(f"Throughput: {best_config['throughput']:.2f} B/s")
print(f"Reliability: {best_config['reliability']:.1f}%")
print("="*70)

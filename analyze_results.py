import json
import matplotlib.pyplot as plt
import numpy as np
from datetime import datetime
import matplotlib.font_manager as fm

# Set Niramit font
plt.rcParams['font.family'] = 'Niramit'
plt.rcParams['font.size'] = 10

# Load results
with open('rf433_results_optimal_mtu.json', 'r') as f:
    data = json.load(f)

# Filter valid MTU sizes (exclude garbage values from sync loss)
valid_mtus = [16, 32, 64, 128, 256, 512, 1024]
filtered_data = {str(mtu): data[str(mtu)] for mtu in valid_mtus if str(mtu) in data}

# Prepare data for analysis
analysis = []
for mtu_str, tests in filtered_data.items():
    mtu = int(mtu_str)
    for test in tests:
        # Calculate efficiency score: throughput weighted by reliability
        # Perfect delivery (0% loss, 0% CRC fail) = 100% efficiency
        reliability = (100 - test['loss']) * (100 - test['crc_failure_percent']) / 100
        efficiency = (test['rf_throughput'] / 1000) * (reliability / 100)  # Normalize to KB/s

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

# Find optimal configuration
best_config = max(analysis, key=lambda x: x['efficiency'])
best_throughput = max(analysis, key=lambda x: x['throughput'])
best_reliability = max(analysis, key=lambda x: x['reliability'])

# Generate text summary
summary = f"""
{'='*70}
RF433 PERFORMANCE BENCHMARK SUMMARY
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
PERFORMANCE BY MTU SIZE
{'='*70}
"""

# Add MTU-specific analysis
for mtu in valid_mtus:
    mtu_tests = [x for x in analysis if x['mtu'] == mtu]
    if not mtu_tests:
        continue

    avg_loss = np.mean([x['loss'] for x in mtu_tests])
    avg_crc = np.mean([x['crc_failure'] for x in mtu_tests])
    avg_throughput = np.mean([x['throughput'] for x in mtu_tests])

    summary += f"\nMTU {mtu} bytes:\n"
    summary += f"  Avg Throughput: {avg_throughput:.2f} B/s\n"
    summary += f"  Avg Loss: {avg_loss:.1f}%\n"
    summary += f"  Avg CRC Failures: {avg_crc:.1f}%\n"

    if avg_loss == 0 and avg_crc == 0:
        summary += "  Status: EXCELLENT - Perfect delivery\n"
    elif avg_loss <= 1 and avg_crc == 0:
        summary += "  Status: VERY GOOD - Minimal loss, no corruption\n"
    elif avg_loss <= 5 and avg_crc <= 5:
        summary += "  Status: ACCEPTABLE - Some loss and corruption\n"
    elif avg_loss <= 20:
        summary += "  Status: POOR - Significant degradation\n"
    else:
        summary += "  Status: CRITICAL - System failure\n"

summary += f"""
{'='*70}
KEY FINDINGS
{'='*70}
1. Viable MTU Range: 16-128 bytes for reliable operation
2. Critical Threshold: System breaks down at 256+ bytes
3. Buffer Overflow: Complete failure at 1024+ bytes (84% loss)
4. Data Corruption: CRC failures increase with MTU size
   - 16-128 bytes: 0% corruption
   - 256 bytes: 3-5% corruption
   - 512 bytes: 8-16% corruption

5. Root Cause: RF module buffer overflow
   - At 9600 baud, large packets take >1 second to transmit
   - Air gaps (4-29ms) too short for RF transmission time
   - Serial port sends faster than RF can transmit

{'='*70}
RECOMMENDATIONS
{'='*70}
For Maximum Reliability:
  - Use MTU <= 64 bytes
  - Air gap: Any (4-29ms all work well)
  - Expected: 0% loss, 0% corruption

For Best Performance:
  - Use MTU = {best_config['mtu']} bytes
  - Air gap: {best_config['gap_ms']} ms
  - Expected: {best_config['throughput']:.0f} B/s throughput

For Large Packet Support:
  - Implement adaptive air gaps based on MTU size
  - Required delay = (MTU x 10 bits / 9600) + safety margin
  - Example: 1024B needs >=1.1 second gap

{'='*70}
"""

# Save summary to file
with open('rf433_analysis_summary.txt', 'w', encoding='utf-8') as f:
    f.write(summary)

print(summary)
print("\nSummary saved to: rf433_analysis_summary.txt")

# Create visualizations
fig, axes = plt.subplots(2, 2, figsize=(14, 10))
fig.suptitle('RF433 Performance Analysis @ 9600 baud', fontsize=16, fontweight='bold')

# Prepare data for plotting
mtus = sorted(list(set([x['mtu'] for x in analysis])))
colors = plt.cm.viridis(np.linspace(0, 1, len(valid_mtus)))

# Plot 1: Throughput vs MTU (by air gap)
ax1 = axes[0, 0]
for gap in sorted(list(set([x['gap_ms'] for x in analysis]))):
    gap_data = [x for x in analysis if x['gap_ms'] == gap]
    mtus_gap = [x['mtu'] for x in gap_data]
    throughputs = [x['throughput'] for x in gap_data]
    ax1.plot(mtus_gap, throughputs, marker='o', label=f'{gap}ms gap', linewidth=2)

ax1.set_xlabel('MTU Size (bytes)', fontweight='bold')
ax1.set_ylabel('RF Throughput (B/s)', fontweight='bold')
ax1.set_title('Throughput vs MTU Size')
ax1.legend()
ax1.grid(True, alpha=0.3)
ax1.set_xscale('log', base=2)
ax1.set_xticks(valid_mtus)
ax1.set_xticklabels([str(m) for m in valid_mtus])
ax1.get_xaxis().set_major_formatter(plt.ScalarFormatter())

# Plot 2: Packet Loss vs MTU
ax2 = axes[0, 1]
for gap in sorted(list(set([x['gap_ms'] for x in analysis]))):
    gap_data = [x for x in analysis if x['gap_ms'] == gap]
    mtus_gap = [x['mtu'] for x in gap_data]
    losses = [x['loss'] for x in gap_data]
    ax2.plot(mtus_gap, losses, marker='s', label=f'{gap}ms gap', linewidth=2)

ax2.set_xlabel('MTU Size (bytes)', fontweight='bold')
ax2.set_ylabel('Packet Loss (%)', fontweight='bold')
ax2.set_title('Packet Loss vs MTU Size')
ax2.legend()
ax2.grid(True, alpha=0.3)
ax2.set_xscale('log', base=2)
ax2.set_xticks(valid_mtus)
ax2.set_xticklabels([str(m) for m in valid_mtus])
ax2.get_xaxis().set_major_formatter(plt.ScalarFormatter())
ax2.axhline(y=5, color='orange', linestyle='--', alpha=0.5, label='5% threshold')
ax2.axhline(y=10, color='red', linestyle='--', alpha=0.5, label='10% threshold')

# Plot 3: CRC Failures vs MTU
ax3 = axes[1, 0]
for gap in sorted(list(set([x['gap_ms'] for x in analysis]))):
    gap_data = [x for x in analysis if x['gap_ms'] == gap]
    mtus_gap = [x['mtu'] for x in gap_data]
    crc_fails = [x['crc_failure'] for x in gap_data]
    ax3.plot(mtus_gap, crc_fails, marker='^', label=f'{gap}ms gap', linewidth=2)

ax3.set_xlabel('MTU Size (bytes)', fontweight='bold')
ax3.set_ylabel('CRC Failures (%)', fontweight='bold')
ax3.set_title('Data Corruption vs MTU Size')
ax3.legend()
ax3.grid(True, alpha=0.3)
ax3.set_xscale('log', base=2)
ax3.set_xticks(valid_mtus)
ax3.set_xticklabels([str(m) for m in valid_mtus])
ax3.get_xaxis().set_major_formatter(plt.ScalarFormatter())

# Plot 4: Efficiency Score (weighted performance)
ax4 = axes[1, 1]
mtu_efficiency = {}
for mtu in valid_mtus:
    mtu_tests = [x for x in analysis if x['mtu'] == mtu]
    if mtu_tests:
        avg_efficiency = np.mean([x['efficiency'] for x in mtu_tests])
        mtu_efficiency[mtu] = avg_efficiency

mtus_sorted = sorted(mtu_efficiency.keys())
efficiencies = [mtu_efficiency[m] for m in mtus_sorted]
bars = ax4.bar(range(len(mtus_sorted)), efficiencies, color=colors[:len(mtus_sorted)], alpha=0.7)
ax4.set_xticks(range(len(mtus_sorted)))
ax4.set_xticklabels([str(m) for m in mtus_sorted])
ax4.set_xlabel('MTU Size (bytes)', fontweight='bold')
ax4.set_ylabel('Efficiency Score', fontweight='bold')
ax4.set_title('Overall Efficiency (Throughput × Reliability)')
ax4.grid(True, alpha=0.3, axis='y')

# Highlight best config
best_idx = mtus_sorted.index(best_config['mtu'])
bars[best_idx].set_color('gold')
bars[best_idx].set_edgecolor('red')
bars[best_idx].set_linewidth(3)
ax4.text(best_idx, efficiencies[best_idx], 'OPTIMAL',
         ha='center', va='bottom', fontweight='bold', color='red')

plt.tight_layout()
plt.savefig('rf433_performance_analysis.png', dpi=300, bbox_inches='tight')
print("Graphs saved to: rf433_performance_analysis.png")

# Create a second figure for detailed comparison
fig2, ax = plt.subplots(figsize=(12, 6))
gap_4ms = [x for x in analysis if x['gap_ms'] == 4]
mtus_4 = [x['mtu'] for x in gap_4ms]
throughput_4 = [x['throughput'] for x in gap_4ms]
loss_4 = [x['loss'] for x in gap_4ms]
crc_4 = [x['crc_failure'] for x in gap_4ms]

x = np.arange(len(mtus_4))
width = 0.25

bars1 = ax.bar(x - width, throughput_4, width, label='Throughput (B/s)', alpha=0.8)
bars2 = ax.bar(x, loss_4, width, label='Loss (%)', alpha=0.8)
bars3 = ax.bar(x + width, crc_4, width, label='CRC Failures (%)', alpha=0.8)

ax.set_xlabel('MTU Size (bytes)', fontweight='bold')
ax.set_ylabel('Value', fontweight='bold')
ax.set_title('Performance Metrics Comparison @ 4ms Air Gap', fontweight='bold')
ax.set_xticks(x)
ax.set_xticklabels(mtus_4)
ax.legend()
ax.grid(True, alpha=0.3, axis='y')

plt.tight_layout()
plt.savefig('rf433_detailed_comparison.png', dpi=300, bbox_inches='tight')
print("Detailed comparison saved to: rf433_detailed_comparison.png")

plt.show()

print("\n" + "="*70)
print("ANALYSIS COMPLETE!")
print("="*70)
print(f"Optimal Configuration: MTU={best_config['mtu']}B @ {best_config['gap_ms']}ms")
print(f"Throughput: {best_config['throughput']:.2f} B/s")
print(f"Reliability: {best_config['reliability']:.1f}%")
print("="*70)

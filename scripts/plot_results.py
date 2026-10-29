
import json
from pathlib import Path

# Locate the project root directory
ROOT = Path(__file__).resolve().parent.parent

# Three experimental configurations
RESULT_FILES = {
    "Cheap Baseline": ROOT / "results/default40-20261024T095549Z-866e97e4/batch_summary.json",
    "Expensive Baseline": ROOT / "results/results_expensive/task4_summary.json",
    "Improved Harness": ROOT / "results/Improved-Final-Run/batch_summary.json",
}

results = {}

for name, path in RESULT_FILES.items():
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    tasks = data["tasks"]

    # Include every available official reward, even if status is execution_error
    rewards = [
        t["official_reward"]
        for t in tasks
        if t.get("official_reward") is not None
    ]

    costs = [
        t["cost_usd"]
        for t in tasks
        if t.get("cost_usd") is not None
    ]

    results[name] = {
        "total_tasks": len(tasks),
        "valid_rewards": len(rewards),
        "mean_reward": sum(rewards) / len(rewards),
        "known_cost": sum(costs),
        "missing_costs": len(tasks) - len(costs),
    }

# Display summary
print("\n=== EXPERIMENT RESULTS ===")

for name, r in results.items():
    print(f"\n{name}")
    print(f"Tasks: {r['total_tasks']}")
    print(f"Valid rewards: {r['valid_rewards']}")
    print(f"Mean reward: {r['mean_reward']:.2%}")
    print(f"Known API cost: ${r['known_cost']:.4f}")
    print(f"Missing cost records: {r['missing_costs']}")
# ============================================
# Graph 1: Accuracy-Cost Trade-off & Pareto Frontier
# ============================================
import matplotlib.pyplot as plt

# Prepare data from the three configurations
names = list(results.keys())
costs = [results[name]["known_cost"] for name in names]
rewards = [results[name]["mean_reward"] * 100 for name in names]

colors = ["#3B82F6", "#F59E0B", "#10B981"]

fig, ax = plt.subplots(figsize=(10, 6))

# Plot each configuration
for i, name in enumerate(names):
    ax.scatter(
        costs[i], rewards[i],
        s=180, color=colors[i],
        label=name, zorder=3
    )
    ax.annotate(
        f"{name}\n${costs[i]:.2f} | {rewards[i]:.2f}%",
        (costs[i], rewards[i]),
        xytext=(12, 14 if i == 0 else 8),
        textcoords="offset points",
        fontsize=9
    )

# Compute the observed Pareto frontier automatically:
# Lower cost and higher reward are preferred.
frontier = []
for i in range(len(names)):
    dominated = any(
        costs[j] <= costs[i]
        and rewards[j] >= rewards[i]
        and (costs[j] < costs[i] or rewards[j] > rewards[i])
        for j in range(len(names)) if j != i
    )
    if not dominated:
        frontier.append(i)

frontier.sort(key=lambda i: costs[i])

ax.plot(
    [costs[i] for i in frontier],
    [rewards[i] for i in frontier],
    "--", color="#64748B", linewidth=1.8,
    label="Observed Pareto Frontier"
)

ax.set_title("Accuracy-Cost Trade-off Across Harness Configurations",
             fontsize=14, fontweight="bold")
ax.set_xlabel("Recorded API Cost per 40-Task Batch (USD)")
ax.set_ylabel("Mean Official Reward (%)")
ax.set_xlim(0.5, max(costs) + 1)
ax.set_ylim(0, max(rewards) + 12)
ax.grid(alpha=0.2)
ax.legend(loc="upper left")

fig.text(
    0.5, 0.01,
    "Mean reward: 38 available scores per configuration. "
    "Expensive baseline: 2 missing cost records.",
    ha="center", fontsize=8, color="dimgray"
)
fig.tight_layout(rect=[0, 0.05, 1, 1])

# Save the graph
output_dir = ROOT / "figures"
output_dir.mkdir(exist_ok=True)

output_path = output_dir / "accuracy_cost.png"
plt.savefig(output_path, dpi=300, bbox_inches="tight")
plt.show()

print(f"\nGraph saved to: {output_path}")
import csv

table_path = output_dir / "summary_table.csv"

with open(table_path, "w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    writer.writerow([
        "Configuration",
        "Total Tasks",
        "Valid Rewards",
        "Mean Reward (%)",
        "Known API Cost (USD)",
        "Missing Cost Records"
    ])

    for name, r in results.items():
        writer.writerow([
            name,
            r["total_tasks"],
            r["valid_rewards"],
            round(r["mean_reward"] * 100, 2),
            round(r["known_cost"], 4),
            r["missing_costs"]
        ])

print(f"Summary table saved to: {table_path}")

# ============================================
# Graph 2: Main Results Table
# ============================================

# Prepare table data from JSON results
table_data = []

for name, r in results.items():
    cost_label = f"${r['known_cost']:.2f}"

    # Mark incomplete cost data
    if r["missing_costs"] > 0:
        cost_label += "*"

    table_data.append([
        name,
        f"{r['mean_reward'] * 100:.2f}%",
        cost_label,
        f"{r['valid_rewards']}/{r['total_tasks']}"
    ])

columns = [
    "Configuration",
    "Mean Reward",
    "Recorded Cost (USD)",
    "Valid Rewards"
]

# Create figure
fig, ax = plt.subplots(figsize=(11, 3.5))
ax.axis("off")

table = ax.table(
    cellText=table_data,
    colLabels=columns,
    cellLoc="center",
    colLoc="center",
    loc="center",
    colWidths=[0.30, 0.21, 0.28, 0.21]
)

# Format table
table.auto_set_font_size(False)
table.set_fontsize(11)
table.scale(1, 2.3)

for (row, col), cell in table.get_celld().items():
    cell.set_edgecolor("#D6DEE8")
    cell.set_linewidth(0.7)

    if row == 0:
        cell.set_facecolor("#243B53")
        cell.get_text().set_color("white")
        cell.get_text().set_weight("bold")
    else:
        cell.set_facecolor(
            "#F1F5F9" if row % 2 == 1 else "white"
        )
        if row == 3:
            cell.get_text().set_weight("bold")

ax.set_title(
    "Main Experimental Results",
    fontsize=17,
    fontweight="bold",
    pad=22
)

fig.text(
    0.5, 0.08,
    "Mean reward is based on 38 available official scores per configuration.\n"
    "* Expensive baseline has 2 missing API cost records.",
    ha="center",
    fontsize=9,
    color="#64748B"
)

table_image_path = output_dir / "summary_table.png"

plt.savefig(
    table_image_path,
    dpi=300,
    bbox_inches="tight",
    facecolor="white"
)

plt.close(fig)

print(f"Results table saved to: {table_image_path}")

# ============================================
# Graph 3: Mean Reward Comparison
# ============================================

names = list(results.keys())
rewards = [
    results[name]["mean_reward"] * 100
    for name in names
]

colors = ["#3B82F6", "#F59E0B", "#10B981"]

fig, ax = plt.subplots(figsize=(10, 6))

bars = ax.bar(
    names,
    rewards,
    color=colors,
    width=0.55
)

# Display values above each bar
for bar, reward in zip(bars, rewards):
    ax.text(
        bar.get_x() + bar.get_width() / 2,
        bar.get_height() + 0.7,
        f"{reward:.2f}%",
        ha="center",
        fontsize=12,
        fontweight="bold"
    )

ax.set_title(
    "Mean Official Reward by Configuration",
    fontsize=16,
    fontweight="bold",
    pad=20
)

ax.set_ylabel("Mean Official Reward (%)")
ax.set_ylim(0, 40)
ax.grid(axis="y", alpha=0.2)
ax.set_axisbelow(True)

fig.text(
    0.5, 0.02,
    "Mean reward calculated from 38 available official scores "
    "per configuration; single run per configuration.",
    ha="center",
    fontsize=9,
    color="dimgray"
)

fig.tight_layout(rect=[0, 0.06, 1, 1])

reward_path = output_dir / "reward_comparison.png"

plt.savefig(
    reward_path,
    dpi=300,
    bbox_inches="tight",
    facecolor="white"
)

plt.close(fig)

print(f"Reward comparison saved to: {reward_path}")

# ============================================
# Graph 4: API Cost Comparison
# ============================================

names = list(results.keys())
costs = [results[name]["known_cost"] for name in names]

colors = ["#3B82F6", "#F59E0B", "#10B981"]

fig, ax = plt.subplots(figsize=(10, 6))

bars = ax.bar(
    names,
    costs,
    color=colors,
    width=0.55
)

# Add cost labels above each bar
for i, (bar, cost) in enumerate(zip(bars, costs)):
    label = f"${cost:.2f}"

    if results[names[i]]["missing_costs"] > 0:
        label += "*"

    ax.text(
        bar.get_x() + bar.get_width() / 2,
        bar.get_height() + 0.12,
        label,
        ha="center",
        fontsize=12,
        fontweight="bold"
    )

ax.set_title(
    "Recorded API Cost by Configuration",
    fontsize=16,
    fontweight="bold",
    pad=20
)

ax.set_ylabel("Recorded API Cost per 40-Task Batch (USD)")
ax.set_ylim(0, max(costs) * 1.2)
ax.grid(axis="y", alpha=0.2)
ax.set_axisbelow(True)

fig.text(
    0.5, 0.02,
    "Costs include all available task records. "
    "* Expensive baseline has 2 missing cost records.",
    ha="center",
    fontsize=9,
    color="dimgray"
)

fig.tight_layout(rect=[0, 0.06, 1, 1])

cost_path = output_dir / "cost_comparison.png"

plt.savefig(
    cost_path,
    dpi=300,
    bbox_inches="tight",
    facecolor="white"
)

plt.close(fig)

print(f"Cost comparison saved to: {cost_path}")

# ============================================
# Graph 5: Improved Harness Cost Outlier
# ============================================

improved_path = RESULT_FILES["Improved Harness"]

with open(improved_path, "r", encoding="utf-8") as f:
    improved_data = json.load(f)

tasks = improved_data["tasks"]

# Sort tasks by recorded API cost
sorted_tasks = sorted(
    [t for t in tasks if t.get("cost_usd") is not None],
    key=lambda t: t["cost_usd"],
    reverse=True
)

# Show the five most expensive tasks
top_tasks = sorted_tasks[:5]

task_names = [t["task_id"] for t in top_tasks]
task_costs = [t["cost_usd"] for t in top_tasks]

# Shorten labels
short_names = [
    name.split("-", 1)[1] for name in task_names
]

colors = ["#EF4444"] + ["#3B82F6"] * 4

fig, ax = plt.subplots(figsize=(11, 6))

bars = ax.barh(
    short_names[::-1],
    task_costs[::-1],
    color=colors[::-1]
)

for bar in bars:
    ax.text(
        bar.get_width() + 0.03,
        bar.get_y() + bar.get_height() / 2,
        f"${bar.get_width():.3f}",
        va="center",
        fontsize=10
    )

ax.set_xlim(0, max(task_costs) * 1.2)
ax.set_xlabel("Recorded API Cost (USD)")
ax.set_title(
    "Top 5 Most Expensive Tasks - Improved Harness",
    fontsize=15,
    fontweight="bold",
    pad=20
)

ax.grid(axis="x", alpha=0.2)
ax.set_axisbelow(True)

fig.tight_layout()

outlier_path = output_dir / "cost_outlier.png"
plt.savefig(outlier_path, dpi=300, bbox_inches="tight")
plt.close(fig)

print(f"Cost outlier graph saved to: {outlier_path}")

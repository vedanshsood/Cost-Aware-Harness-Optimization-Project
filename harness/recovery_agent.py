"""Compatibility layer for the original recovery variant.

The teammate's original recovery guidance is preserved below.

This version passes the original task instruction unchanged to
Harbor Terminus-2. The guidance is not appended automatically.

BoundedTerminus2 can continue inheriting from this class and adding
its idle guard, artifact checks, and completion-time guidance.
"""

from harbor.agents.terminus_2.terminus_2 import Terminus2
from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext


# Preserved from the teammate's original recovery variant.
# Retained for attribution and comparison; not injected by run().
RECOVERY_GUIDANCE = """
Harness recovery protocol:
- Before changing a supplied file, inspect the relevant source data and write a
  short checklist from the task's exact requirements. Use supplied files as the
  source of truth; do not invent facts, records, addresses, or values to fill a
  gap. If required information is missing, state that limitation.
- After each meaningful change, inspect the resulting terminal or application state.
- Compare what you observe with the requested outcome before moving on.
- If a command leaves a shell continuation prompt such as `>` or `quote>`, treat
  the command as unfinished. Send `C-c` as the terminal's special control-key
  sequence, not as text in a shell command, and confirm the normal shell prompt
  returns before issuing another command. If it does not, send `C-c` once more;
  if the shell is still stuck, stop and explain the blocker instead of marking
  the task complete.
- If the action failed or only partly worked, identify the likely cause, make one
  corrected attempt, and inspect the result again.
- Do not repeat a failed action unchanged. If recovery is not possible, explain
  the blocker and leave the environment in the safest useful state.
- Before reporting completion, verify the requested end state from observable
  evidence. Do not claim success based only on issuing commands.
- Verify each checklist item against the saved deliverable with a suitable
  reader for its format. Check required names, values, structure, and output
  location; for calculations, independently recompute key totals or percentages
  from the supplied data when practical. If a requirement fails, correct it and
  inspect the saved deliverable again.
""".strip()


class RecoveryTerminus2(Terminus2):
    """Preserve the inheritance interface without altering the instruction."""

    async def run(
        self,
        instruction: str,
        environment: BaseEnvironment,
        context: AgentContext,
    ) -> None:
        await super().run(
            instruction=instruction,
            environment=environment,
            context=context,
        )
"""Three baselines, in increasing order of how hard they are to beat."""

from .first_valid import run as run_first_valid
from .rejection import run as run_rejection
from .single_prompt import run as run_single_prompt

BASELINES = {
    "rejection": run_rejection,
    "single_prompt": run_single_prompt,
    "first_valid": run_first_valid,
}

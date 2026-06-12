from .ranking_param_tuning import RankingParamTuningExecutor
from .prompt_tuning import PromptTuningExecutor


EXECUTORS = {
    "prompt_tuning": PromptTuningExecutor,
    "ranking_param_tuning": RankingParamTuningExecutor,
}

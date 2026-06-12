from .model_param_tuning import ModelParamTuningExecutor
from .ranking_param_tuning import RankingParamTuningExecutor
from .prompt_tuning import PromptTuningExecutor


EXECUTORS = {
    "model_param_tuning": ModelParamTuningExecutor,
    "prompt_tuning": PromptTuningExecutor,
    "ranking_param_tuning": RankingParamTuningExecutor,
}

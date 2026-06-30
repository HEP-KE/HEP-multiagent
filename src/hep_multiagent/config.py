DEFAULT_EXTENSIONS = [".hdf5", ".h5", ".fits", ".csv", ".png", ".pdf", ".jpg", ".txt"]
DEFAULT_OUTPUT_DIR = "./output"

from .workers.data import PROMPT as DATA_WORKER, get_data_tools
from .workers.compute import PROMPT as COMPUTE_WORKER, get_compute_tools
from .workers.research import PROMPT as RESEARCH_WORKER, get_research_tools
from .workers.viz import PROMPT as VIZ_WORKER, get_viz_tools

WORKERS = {
    "data": DATA_WORKER,
    "compute": COMPUTE_WORKER,
    "research": RESEARCH_WORKER,
    "viz": VIZ_WORKER,
}

WORKER_TOOLS = {
    "data": get_data_tools,
    "compute": get_compute_tools,
    "research": get_research_tools,
    "viz": get_viz_tools,
}

from .consultants import arxiv, data as data_consultant, file as file_consultant

CONSULTANTS = {
    "arxiv": arxiv,
    "data": data_consultant,
    "file": file_consultant,
}

from .features.report_generator import LaTeXReport

REPORTS = {
    "latex": LaTeXReport,
}

from .features.citation_builder import BibTeXManager

REFERENCES = {
    "bibtex": BibTeXManager,
}

from .features.replay_notebook import ExecutionNotebook
from .features.session_resume import SQLiteCheckpoint

from .features.human_in_loop import AutoApproval, InterruptApproval

APPROVAL = {
    "auto": AutoApproval,
    "interrupt": InterruptApproval,
}


def get_worker_docs():
    return "\n".join(f"- {name}: {prompt}" for name, prompt in WORKERS.items())

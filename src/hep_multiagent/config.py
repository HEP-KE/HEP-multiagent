from .consultants import arxiv, data as data_consultant, file as file_consultant
from .features.citation_builder import BibTeXManager
from .features.replay_notebook import ExecutionNotebook
from .features.report_generator import LaTeXReport
from .features.session_resume import SQLiteCheckpoint
from .workers.compute import PROMPT as COMPUTE_WORKER, get_compute_tools
from .workers.data import PROMPT as DATA_WORKER, get_data_tools
from .workers.research import PROMPT as RESEARCH_WORKER, get_research_tools
from .workers.viz import PROMPT as VIZ_WORKER, get_viz_tools


DEFAULT_EXTENSIONS = [".hdf5", ".h5", ".fits", ".csv", ".png", ".pdf", ".jpg", ".txt"]
DEFAULT_OUTPUT_DIR = "./output"

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

CONSULTANTS = {
    "arxiv": arxiv,
    "data": data_consultant,
    "file": file_consultant,
}

REPORTS = {
    "latex": LaTeXReport,
}

REFERENCES = {
    "bibtex": BibTeXManager,
}

def get_worker_docs(worker_types=None):
    names = worker_types or WORKERS
    return "\n".join(f"- {name}: {WORKERS[name]}" for name in names)


def get_worker_tools(worker_type, output_dir, available_tools=None):
    return WORKER_TOOLS[worker_type](output_dir, available_tools)

from .compute import _execute_python_impl, inspect_datafile as _inspect_datafile, _write_csv_impl
from .research import web_search as _web_search, get_arxiv_metadata as _get_arxiv_metadata, cite as _cite
from .research import search_arxiv_abstracts as _search_arxiv_abstracts, download_arxiv_full_text as _download_arxiv_full_text, read_arxiv_chunk as _read_arxiv_chunk
from ..features.agent_tools import list_output_files as _list_output_files

# execute_python / write_csv_file are per-run closures in production; the replay
# notebook re-runs recorded tool calls standalone, so it imports these plain
# implementations (which take output_dir explicitly) instead.
execute_python = _execute_python_impl
inspect_datafile = _inspect_datafile.func
write_csv_file = _write_csv_impl
web_search = _web_search.func
get_arxiv_metadata = _get_arxiv_metadata.func
cite = _cite.func
search_arxiv_abstracts = _search_arxiv_abstracts.func
download_arxiv_full_text = _download_arxiv_full_text.func
read_arxiv_chunk = _read_arxiv_chunk.func
list_output_files = _list_output_files.func

__all__ = [
    "execute_python", "inspect_datafile", "write_csv_file",
    "web_search", "get_arxiv_metadata", "cite",
    "search_arxiv_abstracts", "download_arxiv_full_text", "read_arxiv_chunk",
    "list_output_files",
]

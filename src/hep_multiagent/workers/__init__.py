from .compute import execute_python as _execute_python, inspect_datafile as _inspect_datafile, save_json as _save_json
from .research import web_search as _web_search, get_arxiv_metadata as _get_arxiv_metadata, cite as _cite
from .research import search_arxiv_abstracts as _search_arxiv_abstracts, download_arxiv_full_text as _download_arxiv_full_text, read_arxiv_chunk as _read_arxiv_chunk
from .viz import list_data_keys as _list_data_keys, create_bar_chart as _create_bar_chart
from .viz import create_histogram as _create_histogram, create_scatter_plot as _create_scatter_plot, create_line_plot as _create_line_plot

execute_python = _execute_python.func
inspect_datafile = _inspect_datafile.func
save_json = _save_json.func
web_search = _web_search.func
get_arxiv_metadata = _get_arxiv_metadata.func
cite = _cite.func
search_arxiv_abstracts = _search_arxiv_abstracts.func
download_arxiv_full_text = _download_arxiv_full_text.func
read_arxiv_chunk = _read_arxiv_chunk.func
list_data_keys = _list_data_keys.func
create_bar_chart = _create_bar_chart.func
create_histogram = _create_histogram.func
create_scatter_plot = _create_scatter_plot.func
create_line_plot = _create_line_plot.func

__all__ = [
    "execute_python", "inspect_datafile", "save_json",
    "web_search", "get_arxiv_metadata", "cite",
    "search_arxiv_abstracts", "download_arxiv_full_text", "read_arxiv_chunk",
    "list_data_keys", "create_bar_chart", "create_histogram", "create_scatter_plot", "create_line_plot",
]

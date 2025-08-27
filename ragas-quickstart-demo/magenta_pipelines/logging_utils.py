import contextlib
from io import StringIO

from rich.console import Console
from rich.errors import NotRenderableError
from rich.table import Table


def render_dataframe_as_table(df, title="Evaluation Results") -> str:
    """Render dataframe as a rich table for logging.

    Args:
        df: pandas DataFrame to render
        title: Title for the table

    Returns:
        String representation of the rich table
    """
    string_buffer = StringIO()
    console = Console(file=string_buffer, width=120)

    df_str = df.astype(str)

    table = Table(title=title)

    for col in df_str.columns:
        table.add_column(col, justify="left")

    for row in df_str.values:
        with contextlib.suppress(NotRenderableError):
            table.add_row(*row)

    console.print(table)
    return string_buffer.getvalue()

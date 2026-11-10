"""Data Explorer tab: browse the synthetic tables, the data dictionary, and download CSVs."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from molarmetrics.data.dictionary import COLUMNS, TABLE_DESCRIPTIONS
from molarmetrics.data.schema import TABLE_ORDER


@st.cache_data(show_spinner=False)
def _load_csv(path: str, mtime_ns: int) -> pd.DataFrame:
    return pd.read_csv(path, dtype={"tooth_number": "Int64"})


def render_explorer(data_dir: Path) -> None:
    csv_dir = data_dir / "csv"
    st.markdown("Browse the generated tables. Every row is **synthetic**: fictional patients (no names or contact "
                "details), fictional dentists, and invented fees.")
    left, right = st.columns([1, 3], vertical_alignment="bottom")
    table = left.selectbox("Table", TABLE_ORDER, format_func=lambda t: t.capitalize())
    path = csv_dir / f"molarmetrics_{table}.csv"
    if not path.exists():
        st.error(f"{path.name} not found. Generate the data with: python -m molarmetrics.data.generate")
        return
    df = _load_csv(str(path), path.stat().st_mtime_ns)
    right.caption(f"{TABLE_DESCRIPTIONS[table]}  ·  {len(df):,} rows × {len(df.columns)} columns")

    st.dataframe(df, hide_index=True, width="stretch", height=380)
    st.download_button(f"Download {path.name}", data=path.read_bytes(), file_name=path.name, mime="text/csv",
                       key=f"dl_{table}", on_click="ignore", icon=":material/download:")

    st.markdown(f"**Data dictionary: `{table}`**")
    dictionary = pd.DataFrame([{"Column": c, "Type": ty, "Description": d}
                               for t, c, ty, d in COLUMNS if t == table])
    st.dataframe(dictionary, hide_index=True, width="stretch")

    with st.expander("All downloads", icon=":material/folder_zip:"):
        cols = st.columns(3)
        for i, t in enumerate(TABLE_ORDER):
            p = csv_dir / f"molarmetrics_{t}.csv"
            if p.exists():
                cols[i % 3].download_button(p.name, data=p.read_bytes(), file_name=p.name, mime="text/csv",
                                            key=f"dl_all_{t}", on_click="ignore", width="stretch")
        for name, mime in (("molarmetrics_data_dictionary.md", "text/markdown"),
                           ("molarmetrics_data_dictionary.csv", "text/csv"),
                           ("molarmetrics_validation_report.json", "application/json")):
            p = data_dir / name
            if p.exists():
                st.download_button(name, data=p.read_bytes(), file_name=name, mime=mime, key=f"dl_{name}",
                                   on_click="ignore")

"""Clean Air lab bench.

INTERNAL TOOL. This is where we look at fits, bad stints and diagnostics while
building. It is deliberately ugly and it is never demoed to the judges -- the
demo is the React app in web/.

Run:  streamlit run app/lab.py
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from cleanair.config import CONVENTIONAL_2026, PROCESSED

st.set_page_config(page_title="Clean Air lab", layout="wide")
st.title("Clean Air — lab bench")
st.caption("Internal. Not the demo. The demo is web/.")

dataset = PROCESSED / "laps.parquet"

if not dataset.exists():
    st.warning(f"No dataset yet. Run `python scripts/02_build_dataset.py` to create {dataset}.")
    st.stop()

df = pd.read_parquet(dataset)

c1, c2, c3, c4 = st.columns(4)
c1.metric("laps", f"{len(df):,}")
c2.metric("long-run laps", f"{int(df.get('is_long_run', pd.Series(dtype=bool)).sum()):,}")
c3.metric("drivers", df.Driver.nunique())
c4.metric("events", df.event.nunique())

with st.sidebar:
    st.header("filters")
    events = st.multiselect("event", sorted(df.event.unique()), default=list(CONVENTIONAL_2026[:2]))
    sessions = st.multiselect("session", sorted(df.session.unique()), default=["FP2"])
    compounds = st.multiselect("compound", sorted(df.Compound.dropna().unique()))
    long_only = st.checkbox("long runs only", value=True)

sel = df.copy()
if events:
    sel = sel[sel.event.isin(events)]
if sessions:
    sel = sel[sel.session.isin(sessions)]
if compounds:
    sel = sel[sel.Compound.isin(compounds)]
if long_only and "is_long_run" in sel.columns:
    sel = sel[sel.is_long_run]

st.subheader(f"{len(sel):,} laps selected")

tab_scatter, tab_runs, tab_table = st.tabs(["lap time vs tyre life", "runs", "table"])

with tab_scatter:
    if sel.empty:
        st.info("nothing selected")
    else:
        st.scatter_chart(sel, x="TyreLife", y="LapTimeSeconds", color="Compound", height=440)
        st.caption(
            "Raw, still confounded. Fuel burn pulls this down and tyre wear pushes it up, "
            "so any slope you see here is a blend, not a degradation rate."
        )

with tab_runs:
    if "run_id" not in sel.columns or sel.empty:
        st.info("no run labels — rebuild the dataset")
    else:
        runs = (
            sel.groupby(["event", "session", "Driver", "Compound", "run_id"], as_index=False)
            .agg(laps=("LapNumber", "size"),
                 first_lap=("LapNumber", "min"),
                 mean_time=("LapTimeSeconds", "mean"))
            .sort_values("laps", ascending=False)
        )
        st.dataframe(runs, use_container_width=True, height=440)

with tab_table:
    st.dataframe(sel, use_container_width=True, height=440)

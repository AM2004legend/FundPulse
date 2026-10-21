"""Altair line/area charts with a hover crosshair.

Spec (from the project's data-viz rules): 2px lines, one y-axis only, area fills as a ~10%
wash, series colours from a validated palette in a fixed order (fund 1 = blue, fund 2 =
orange), a legend only when there are two series, and a tooltip on hover.
"""

import altair as alt
import pandas as pd
import streamlit as st

# Validated categorical slots 1-2 (CVD-safe in both modes); dark steps for the dark theme.
SERIES_COLORS = {"light": ["#2a78d6", "#eb6834"], "dark": ["#3987e5", "#d95926"]}
CROSSHAIR = "#898781"  # muted ink: recessive, never a data colour


def _palette() -> list[str]:
    theme = getattr(st.context, "theme", None)
    return SERIES_COLORS["dark" if getattr(theme, "type", None) == "dark" else "light"]


def line_chart(
    df: pd.DataFrame,
    y: str,
    y_title: str,
    y_format: str,
    names: list[str],
    area: bool = False,
) -> alt.LayerChart:
    """df needs nav_date, fund (display name) and the `y` column; one line per fund.

    `names` fixes the colour order: the fund the user picked first is always slot 1 (blue),
    whatever order the rows arrive in. Colour follows the fund, never its position in data.
    """
    df = df.assign(nav_date=pd.to_datetime(df["nav_date"]))
    scale = alt.Scale(domain=names, range=_palette()[: len(names)])
    legend = alt.Legend(title=None, orient="top") if len(names) > 1 else None
    x = alt.X("nav_date:T", title=None)
    y_enc = alt.Y(f"{y}:Q", title=y_title, axis=alt.Axis(format=y_format), stack=None)
    y_enc = y_enc.scale(zero=area)  # NAV lines float; drawdown areas fill down from 0
    base = alt.Chart(df).encode(x=x)

    hover = alt.selection_point(
        fields=["nav_date"], nearest=True, on="pointerover", clear="pointerout", empty=False
    )
    layers = []
    if area:  # the faint wash gets no legend; the legend's swatch comes from the 2px line
        layers.append(
            base.mark_area(opacity=0.1).encode(
                y=y_enc, color=alt.Color("fund:N", scale=scale, legend=None)
            )
        )
    layers.append(
        base.mark_line(strokeWidth=2, strokeCap="round", strokeJoin="round").encode(
            y=y_enc, color=alt.Color("fund:N", scale=scale, legend=legend)
        )
    )
    layers.append(
        base.mark_point(filled=True, size=64, opacity=1)
        .encode(y=y_enc, color=alt.Color("fund:N", scale=scale, legend=None))
        .transform_filter(hover)
    )

    # One tooltip per date listing every fund: pivot to one column per fund (f0, f1).
    wide = df.pivot_table(index="nav_date", columns="fund", values=y, aggfunc="first")
    wide = wide.reindex(columns=names).reset_index()
    wide.columns = ["nav_date"] + [f"f{i}" for i in range(len(names))]
    tooltip = [alt.Tooltip("nav_date:T", title="Date", format="%d %b %Y")] + [
        alt.Tooltip(f"f{i}:Q", title=name, format=y_format) for i, name in enumerate(names)
    ]
    layers.append(
        alt.Chart(wide)
        .mark_rule(color=CROSSHAIR, strokeWidth=1)
        .encode(
            x=x,
            opacity=alt.condition(hover, alt.value(1), alt.value(0)),
            tooltip=tooltip,
        )
        .add_params(hover)
    )
    return alt.layer(*layers).properties(height=320)

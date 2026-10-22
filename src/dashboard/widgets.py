"""Lakeview (AI/BI) widget, filter and page builders.

Widget field expressions are only plain columns or SUM/COUNT/AVG/MIN/MAX of a column; ratios, conditions and text are
computed in the dataset SQL. Counters, tables and symbol maps are spec version 2, bar, line, area, scatter, heatmap and
histogram version 3, choropleth and box version 1.
"""


class Builder:
    """Holds the dashboard's datasets and parameters so filters can bind to every dataset that takes a parameter."""

    def __init__(self, defaults, option_fields):
        self.defaults = defaults
        self.option_fields = option_fields
        self.datasets = []
        self.params = {}
        self._n = 0

    # ------------------------------------------------------------------ datasets
    def dataset(self, name, display, sql, params=()):
        self.params[name] = list(params)
        lines = sql.strip().split("\n")
        self.datasets.append({
            "name": name, "displayName": display,
            "queryLines": [line + "\n" for line in lines[:-1]] + [lines[-1]],
            "parameters": [self._param(p) for p in params],
        })

    def _param(self, keyword):
        return {"displayName": keyword, "keyword": keyword, "dataType": "STRING",
                "defaultSelection": {"values": {"dataType": "STRING", "values": [{"value": self.defaults[keyword]}]}}}

    # ------------------------------------------------------------------ helpers
    def uid(self, prefix):
        self._n += 1
        return f"{prefix}_{self._n:03d}"


def bt(column):
    return f"`{column}`"


def frame(title, desc=None, show_title=True, show_desc=True, align=None):
    value = {"showTitle": show_title, "title": title}
    if desc:
        value.update({"showDescription": show_desc, "description": desc})
    if align:
        value["contentAlignment"] = align
    return value


def query(dataset, fields, disaggregated):
    return [{"name": "main_query", "query": {"datasetName": dataset,
                                             "fields": [{"name": n, "expression": e} for n, e in fields],
                                             "disaggregated": disaggregated}}]


def num(places=0, compact=False):
    value = {"type": "number-plain", "decimalPlaces": {"type": "max", "places": places}}
    if compact:
        value.update({"type": "number", "abbreviation": "compact"})
    return value


def pct(places=1):
    return {"type": "number-percent", "decimalPlaces": {"type": "max", "places": places}}


def agg(fn, column):
    return f"{fn.lower()}({column})", f"{fn.upper()}({bt(column)})"


def cat(field, label, order=None, mappings=None, sort_by=None, size=None, legend=None):
    scale = {"type": "categorical"}
    if size:
        scale["categorySize"] = {"type": "number-of-categories", "number": size}
    if order:
        scale["sort"] = {"by": "custom-order", "orderedValues": order}
    elif sort_by:
        scale["sort"] = {"by": sort_by}
    if mappings:
        scale["mappings"] = mappings
    value = {"fieldName": field, "scale": scale, "displayName": label}
    if legend:
        value["legend"] = legend
    return value


def quant(field, label, fmt=None):
    value = {"fieldName": field, "scale": {"type": "quantitative"}, "displayName": label}
    if fmt:
        value["format"] = fmt
    return value


def ref_line(axis, value, label):
    return {"type": "horizontal-line" if axis == "y" else "vertical-line",
            "encodings": {axis: {"dataValue": str(value), "dataType": "DOUBLE"}, "label": {"value": label},
                          "color": {"value": "#A32D2D"}}}


def text(b, *lines):
    return {"name": b.uid("text"), "multilineTextboxSpec": {"lines": list(lines)}}


def chart(b, kind, dataset, title, encodings, fields, desc=None, disaggregated=False, mark=None, annotations=None,
          version=3):
    spec = {"version": version, "widgetType": kind, "encodings": encodings, "frame": frame(title, desc)}
    if mark:
        spec["mark"] = mark
    if annotations:
        spec["annotations"] = annotations
    return {"name": b.uid(kind.replace("-", "_")), "queries": query(dataset, fields, disaggregated), "spec": spec}


def kpi(b, dataset, title, column, fmt=None, template=None, desc=None, extra=(), target=None, target_label=None,
        style=None, heading=False, align=None, card_style=None):
    """Counter on a one-row dataset; extra columns feed the template. A heading shows only its value, styled large or
    small, with the title and description hidden."""
    fields = [(column, bt(column))] + [(c, bt(c)) for c in extra]
    value = {"fieldName": column, "displayName": title}
    if fmt:
        value["format"] = fmt
    if template:
        value["formatTemplate"] = template
    if style:
        value["style"] = style
    encodings = {"value": value}
    if target:
        fields.append((target, bt(target)))
        encodings["target"] = {"fieldName": target, "displayName": target_label}
        if fmt:
            encodings["target"]["format"] = fmt
    spec = {"version": 2, "widgetType": "counter", "encodings": encodings,
            "frame": frame(title, desc, not heading, not heading, align)}
    if card_style:
        spec["style"] = card_style
    return {"name": b.uid("kpi"), "queries": query(dataset, fields, True), "spec": spec}


def note(b, dataset, title, column, desc=None, style=None, show_title=True, label=None):
    """A counter that shows one sentence (a finding or an answer), not a KPI."""
    value = {"fieldName": column, "displayName": label or title}
    if style:
        value["style"] = style
    return {"name": b.uid("note"), "queries": query(dataset, [(column, bt(column))], True),
            "spec": {"version": 2, "widgetType": "counter", "encodings": {"value": value},
                     "frame": frame(title, desc, show_title, bool(desc), None if desc else "left")}}


def bar(b, dataset, title, x, x_label, fn, value, value_label, horizontal=True, color=None, color_label=None,
        mappings=None, order=None, color_order=None, fmt=None, layout=None, desc=None, sort_by=None, annotations=None,
        categories_shown=None, legend=None, raw=False):
    """raw draws the dataset's rows as they are, unaggregated, so a natural-order sort keeps the SQL's ORDER BY."""
    name, expression = (value, bt(value)) if raw else agg(fn, value)
    fields = [(x, bt(x)), (name, expression)] + ([(color, bt(color))] if color and color != x else [])
    category = cat(x, x_label, order, None, sort_by, categories_shown)
    measure = quant(name, value_label, fmt)
    encodings = {"x": measure, "y": category} if horizontal else {"x": category, "y": measure}
    if color:
        encodings["color"] = cat(color, color_label, color_order, mappings, legend=legend)
    return chart(b, "bar", dataset, title, encodings, fields, desc, mark={"layout": layout} if layout else None,
                 annotations=annotations, disaggregated=raw)


def line(b, dataset, title, x, x_label, fn, value, value_label, fmt=None, color=None, color_label=None, desc=None,
         kind="line", mappings=None, color_order=None, x_order=None):
    """A time series; with x_order the x axis is categorical in that order (school years, not dates)."""
    name, expression = agg(fn, value)
    fields = [(x, bt(x)), (name, expression)] + ([(color, bt(color))] if color else [])
    x_encoding = (cat(x, x_label, x_order) if x_order
                  else {"fieldName": x, "scale": {"type": "temporal"}, "displayName": x_label})
    encodings = {"x": x_encoding, "y": quant(name, value_label, fmt)}
    if color:
        encodings["color"] = cat(color, color_label, color_order, mappings)
    return chart(b, kind, dataset, title, encodings, fields, desc)


def scatter(b, dataset, title, x, x_label, y, y_label, color, color_label, mappings=None, order=None, size=None,
            size_label=None, tip=None, desc=None, annotations=None, extra=None):
    """tip names each point; extra is the whole tooltip as (field, label) pairs instead."""
    tips = extra or ([(tip, "Name")] if tip else [])
    columns = [x, y, color] + ([size] if size else []) + [c for c, _ in tips]
    encodings = {"x": quant(x, x_label), "y": quant(y, y_label), "color": cat(color, color_label, order, mappings)}
    if size:
        encodings["size"] = quant(size, size_label)
    if tips:
        encodings["extra"] = [{"fieldName": c, "displayName": label} for c, label in tips]
    return chart(b, "scatter", dataset, title, encodings, [(c, bt(c)) for c in dict.fromkeys(columns)], desc,
                 disaggregated=True, annotations=annotations)


def heatmap(b, dataset, title, x, x_label, x_order, y, y_label, y_order, fn, value, value_label, desc=None):
    name, expression = agg(fn, value)
    encodings = {"x": cat(x, x_label, x_order), "y": cat(y, y_label, y_order),
                 "color": {"fieldName": name, "displayName": value_label,
                           "scale": {"type": "quantitative", "colorRamp": {"mode": "custom-sequential",
                                                                           "colors": {"start": "#F3EEE9", "end": "#712B13"}}}}}
    return chart(b, "heatmap", dataset, title, encodings, [(x, bt(x)), (y, bt(y)), (name, expression)], desc)


def choropleth(b, dataset, title, value, value_label, extra, mappings, order, desc=None, legend=None):
    """One colour per category (`mappings`), one shape per place: the boundary is taken once per value and extra, as
    GeoJSON in a field named geo_first(boundary) that a custom region points at."""
    shape = "geo_first(boundary)"
    fields = [(c, bt(c)) for c in dict.fromkeys([value] + [c for c, _ in extra])]
    fields.append((shape, "ST_ASGEOJSON(FIRST(`boundary`))"))
    encodings = {"region": {"regionType": "custom", "fieldName": shape},
                 "color": cat(value, value_label, order, mappings, legend=legend),
                 "extra": [{"fieldName": c, "displayName": label} for c, label in extra]}
    return chart(b, "choropleth-map", dataset, title, encodings, fields, desc, version=1)


def point_map(b, dataset, title, latitude, longitude, color, color_label, mappings, order, extra, desc=None):
    """One point per row at (latitude, longitude), one colour per category; `extra` fields show in the tooltip."""
    columns = [latitude, longitude, color] + [c for c, _ in extra]
    encodings = {"coordinates": {"latitude": {"fieldName": latitude}, "longitude": {"fieldName": longitude}},
                 "color": cat(color, color_label, order, mappings),
                 "extra": [{"fieldName": c, "displayName": label} for c, label in extra]}
    return chart(b, "symbol-map", dataset, title, encodings, [(c, bt(c)) for c in dict.fromkeys(columns)], desc,
                 disaggregated=True, mark={"opacity": 0.8}, version=2)


def table(b, dataset, title, columns, desc=None):
    """columns: (field, header, format or None)."""
    spec_columns = []
    for field, header, fmt in columns:
        column = {"fieldName": field, "displayName": header}
        if fmt:
            column["format"] = fmt
        spec_columns.append(column)
    return chart(b, "table", dataset, title, {"columns": spec_columns}, [(f, bt(f)) for f, _, _ in columns], desc,
                 disaggregated=True, version=2)


def param_filter(b, keyword, title, targets, desc=None, options=None, show_desc=True):
    """Single-select filter bound to one parameter on every target dataset that takes it. `options` names a page's own
    (dataset, field) for the choices when the default option dataset is shared with another page's filter."""
    option_dataset, option_field = options or b.option_fields[keyword]
    queries = [{"name": f"opt_{option_dataset}", "query": {"datasetName": option_dataset,
                                                           "fields": [{"name": option_field, "expression": bt(option_field)}],
                                                           "disaggregated": False}}]
    fields = [{"fieldName": option_field, "displayName": title, "queryName": f"opt_{option_dataset}"}]
    for target in targets:
        if keyword not in b.params[target]:
            continue
        name = f"param_{target}_{keyword}"
        queries.append({"name": name, "query": {"datasetName": target, "parameters": [{"name": keyword, "keyword": keyword}],
                                                "disaggregated": False}})
        fields.append({"parameterName": keyword, "queryName": name})
    return {"name": b.uid("filter"), "queries": queries,
            "spec": {"version": 2, "widgetType": "filter-single-select", "encodings": {"fields": fields},
                     "frame": frame(title, desc, show_desc=show_desc),
                     "selection": {"defaultSelection": {"values": {"dataType": "STRING",
                                                                   "values": [{"value": b.defaults[keyword]}]}}}}}


class Page:
    """A 12-column GRID_V1 page filled row by row."""

    def __init__(self, name, title):
        self.name, self.title, self.items, self.y = name, title, [], 0

    def row(self, widgets, height):
        assert sum(width for _, width in widgets) == 12, (self.name, [width for _, width in widgets])
        x = 0
        for widget, width in widgets:
            self.items.append({"widget": widget, "position": {"x": x, "y": self.y, "width": width, "height": height}})
            x += width
        self.y += height

    def columns(self, columns, height):
        """Side-by-side columns of stacked widgets: columns are (width, [(widget, height), ...]), each column at most
        `height` rows."""
        assert sum(width for width, _ in columns) == 12, (self.name, [width for width, _ in columns])
        x = 0
        for width, stack in columns:
            assert sum(h for _, h in stack) <= height, (self.name, [h for _, h in stack])
            y = self.y
            for widget, h in stack:
                self.items.append({"widget": widget, "position": {"x": x, "y": y, "width": width, "height": h}})
                y += h
            x += width
        self.y += height

    def json(self, page_type="PAGE_TYPE_CANVAS"):
        return {"name": self.name, "displayName": self.title, "pageType": page_type, "layoutVersion": "GRID_V1",
                "layout": self.items}

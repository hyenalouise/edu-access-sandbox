"""Lakeview (AI/BI) widget, filter and page builders.

Widget field expressions are only plain columns or SUM/COUNT/AVG/MIN/MAX of a column; ratios, conditions and text are
computed in the dataset SQL. Counters and tables are spec version 2, bar, line, area, scatter, heatmap and histogram
version 3, choropleth and box version 1.
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


def frame(title, desc=None):
    value = {"showTitle": True, "title": title}
    if desc:
        value.update({"showDescription": True, "description": desc})
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


def cat(field, label, order=None, mappings=None, sort_by=None):
    scale = {"type": "categorical"}
    if order:
        scale["sort"] = {"by": "custom-order", "orderedValues": order}
    elif sort_by:
        scale["sort"] = {"by": sort_by}
    if mappings:
        scale["mappings"] = mappings
    return {"fieldName": field, "scale": scale, "displayName": label}


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


def kpi(b, dataset, title, column, fmt=None, template=None, desc=None, extra=(), target=None, target_label=None):
    """Counter on a one-row dataset; extra columns feed the template."""
    fields = [(column, bt(column))] + [(c, bt(c)) for c in extra]
    value = {"fieldName": column, "displayName": title}
    if fmt:
        value["format"] = fmt
    if template:
        value["formatTemplate"] = template
    encodings = {"value": value}
    if target:
        fields.append((target, bt(target)))
        encodings["target"] = {"fieldName": target, "displayName": target_label}
        if fmt:
            encodings["target"]["format"] = fmt
    return {"name": b.uid("kpi"), "queries": query(dataset, fields, True),
            "spec": {"version": 2, "widgetType": "counter", "encodings": encodings, "frame": frame(title, desc)}}


def bar(b, dataset, title, x, x_label, fn, value, value_label, horizontal=True, color=None, color_label=None,
        mappings=None, order=None, color_order=None, fmt=None, layout=None, desc=None, sort_by=None, annotations=None):
    name, expression = agg(fn, value)
    fields = [(x, bt(x)), (name, expression)] + ([(color, bt(color))] if color and color != x else [])
    category = cat(x, x_label, order, None, sort_by)
    measure = quant(name, value_label, fmt)
    encodings = {"x": measure, "y": category} if horizontal else {"x": category, "y": measure}
    if color:
        encodings["color"] = cat(color, color_label, color_order, mappings)
    return chart(b, "bar", dataset, title, encodings, fields, desc, mark={"layout": layout} if layout else None,
                 annotations=annotations)


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
            size_label=None, tip=None, desc=None, annotations=None):
    columns = [x, y, color] + ([size] if size else []) + ([tip] if tip else [])
    encodings = {"x": quant(x, x_label), "y": quant(y, y_label), "color": cat(color, color_label, order, mappings)}
    if size:
        encodings["size"] = quant(size, size_label)
    if tip:
        encodings["extra"] = [{"fieldName": tip, "displayName": "Name"}]
    return chart(b, "scatter", dataset, title, encodings, [(c, bt(c)) for c in dict.fromkeys(columns)], desc,
                 disaggregated=True, annotations=annotations)


def heatmap(b, dataset, title, x, x_label, x_order, y, y_label, y_order, fn, value, value_label, desc=None):
    name, expression = agg(fn, value)
    encodings = {"x": cat(x, x_label, x_order), "y": cat(y, y_label, y_order),
                 "color": {"fieldName": name, "displayName": value_label,
                           "scale": {"type": "quantitative", "colorRamp": {"mode": "custom-sequential",
                                                                           "colors": {"start": "#F3EEE9", "end": "#712B13"}}}}}
    return chart(b, "heatmap", dataset, title, encodings, [(x, bt(x)), (y, bt(y)), (name, expression)], desc)


def choropleth(b, dataset, title, value, value_label, extra, start, end, desc=None):
    fields = [("boundary_geojson", "ST_ASGEOJSON(`boundary`)"), (value, bt(value))] + [(c, bt(c)) for c, _ in extra]
    encodings = {"region": {"regionType": "geometry", "geometry": {"fieldName": "boundary_geojson"}},
                 "color": {"fieldName": value, "displayName": value_label,
                           "scale": {"type": "quantitative", "colorRamp": {"mode": "custom-sequential",
                                                                           "colors": {"start": start, "end": end}}}},
                 "extra": [{"fieldName": c, "displayName": label} for c, label in extra]}
    return chart(b, "choropleth-map", dataset, title, encodings, fields, desc, disaggregated=True, version=1)


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


def param_filter(b, keyword, title, targets, desc=None):
    """Single-select filter bound to one parameter on every target dataset that takes it."""
    option_dataset, option_field = b.option_fields[keyword]
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
                     "frame": frame(title, desc),
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

    def json(self, page_type="PAGE_TYPE_CANVAS"):
        return {"name": self.name, "displayName": self.title, "pageType": page_type, "layoutVersion": "GRID_V1",
                "layout": self.items}

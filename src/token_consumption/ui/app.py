"""
Lightweight local dashboard (FastAPI + Jinja2). Localhost-only by default.

No login (localhost), no external calls, no prompt/output content displayed.
Charts are server-rendered inline SVG — no CDN, no JS framework.
"""

from pathlib import Path

from .. import config as cfg_mod

_TEMPLATES = Path(__file__).parent / "templates"
_STATIC = Path(__file__).parent / "static"


def svg_bar_chart(data: list[dict], label_key: str, value_key: str,
                  width: int = 720, height: int = 220, unit: str = "€") -> str:
    """Render a simple vertical bar chart as an inline SVG string."""
    if not data:
        return '<p class="muted">No data.</p>'
    vals = [d[value_key] or 0 for d in data]
    vmax = max(vals) or 1.0
    n = len(data)
    pad_l, pad_b, pad_t = 40, 42, 10
    plot_w = width - pad_l - 10
    plot_h = height - pad_b - pad_t
    bw = plot_w / n
    bars = []
    for i, d in enumerate(data):
        v = d[value_key] or 0
        bh = (v / vmax) * plot_h
        x = pad_l + i * bw
        y = pad_t + (plot_h - bh)
        label = str(d[label_key])[-5:]
        bars.append(
            f'<rect x="{x+2:.1f}" y="{y:.1f}" width="{max(bw-4,1):.1f}" height="{bh:.1f}" '
            f'class="bar"><title>{label}: {unit}{v:.2f}</title></rect>'
        )
        if n <= 31:
            bars.append(
                f'<text x="{x+bw/2:.1f}" y="{height-pad_b+14:.0f}" class="xlab" '
                f'text-anchor="middle">{label}</text>'
            )
    # y axis max label
    axis = (f'<text x="4" y="{pad_t+8:.0f}" class="ylab">{unit}{vmax:.1f}</text>'
            f'<line x1="{pad_l}" y1="{pad_t+plot_h}" x2="{width-10}" y2="{pad_t+plot_h}" class="axis"/>')
    return (f'<svg viewBox="0 0 {width} {height}" class="chart" '
            f'preserveAspectRatio="xMidYMid meet">{axis}{"".join(bars)}</svg>')


def create_app():
    from fastapi import FastAPI, Request, Form
    from fastapi.responses import HTMLResponse, RedirectResponse
    from fastapi.staticfiles import StaticFiles
    from fastapi.templating import Jinja2Templates

    from . import queries

    app = FastAPI(title="TokenConsumption")
    templates = Jinja2Templates(directory=str(_TEMPLATES))
    if _STATIC.exists():
        app.mount("/static", StaticFiles(directory=str(_STATIC)), name="static")

    def render(request, page, **ctx):
        base = {"page": page, "budget_line": _budget_line()}
        base.update(ctx)
        # Modern Starlette signature: (request, name, context)
        return templates.TemplateResponse(request, f"{page}.html", base)

    def _budget_line():
        from .. import status as status_mod
        try:
            return status_mod.status_line()
        except Exception:
            return "TokenConsumption: (status unavailable)"

    @app.get("/", response_class=HTMLResponse)
    def overview(request: Request):
        ov = queries.overview()
        return render(request, "overview", ov=ov)

    @app.get("/trends", response_class=HTMLResponse)
    def trends(request: Request):
        daily = queries.daily_spend(30)
        by_model = queries.spend_by_model()
        chart = svg_bar_chart(daily, "day", "eur")
        model_chart = svg_bar_chart(
            [{"m": m["model"], "eur": m["eur"] or 0} for m in by_model],
            "m", "eur", width=720, height=200)
        return render(request, "trends", chart=chart, model_chart=model_chart, by_model=by_model)

    @app.get("/projects", response_class=HTMLResponse)
    def projects(request: Request):
        return render(request, "projects", rows=queries.spend_by_project())

    @app.get("/sessions", response_class=HTMLResponse)
    def sessions(request: Request):
        return render(request, "sessions", rows=queries.sessions(100))

    @app.get("/logs", response_class=HTMLResponse)
    def logs(request: Request):
        return render(request, "logs", rows=queries.raw_logs(200))

    @app.get("/settings", response_class=HTMLResponse)
    def settings_get(request: Request):
        return render(request, "settings", cfg=cfg_mod.load(), saved=request.query_params.get("saved"))

    @app.post("/settings")
    def settings_post(
        monthly_budget_value: str = Form(...),
        monthly_budget_currency: str = Form(...),
        safety_threshold_value: str = Form(...),
        safety_threshold_currency: str = Form(...),
        warn_at_percentage_of_threshold: str = Form(...),
        usd_to_eur: str = Form(...),
        account_profile_name: str = Form(...),
    ):
        cfg_mod.set_value("monthly_budget_value", monthly_budget_value)
        cfg_mod.set_value("monthly_budget_currency", monthly_budget_currency)
        cfg_mod.set_value("safety_threshold_value", safety_threshold_value)
        cfg_mod.set_value("safety_threshold_currency", safety_threshold_currency)
        cfg_mod.set_value("warn_at_percentage_of_threshold", warn_at_percentage_of_threshold)
        cfg_mod.set_value("account_profile_name", account_profile_name)
        cur = cfg_mod.load().get("fx_rates", {})
        cur["USD_to_EUR"] = float(usd_to_eur)
        cfg_mod.set_value("fx_rates", __import__("json").dumps(cur))
        return RedirectResponse(url="/settings?saved=1", status_code=303)

    return app


def run_server(host: str = "127.0.0.1", port: int = 8787):
    import uvicorn
    if host not in ("127.0.0.1", "localhost", "::1"):
        print(f"[tc] WARNING: binding to {host} exposes the dashboard beyond localhost.")
    print(f"[tc] TokenConsumption dashboard: http://{host}:{port}  (Ctrl+C to stop)")
    uvicorn.run(create_app(), host=host, port=port, log_level="warning")

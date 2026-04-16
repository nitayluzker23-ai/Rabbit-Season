"""
Rabbit Season — Weekly Earnings Volatility Screener
Runs every Sunday, covers Mon–Wed AMC reports (before Thursday)
Filters: AMC only, Mkt Cap > $20B, Price > $20
Sectors: Technology, Finance, Energy, Biotech/Pharma
"""

import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import requests
from bs4 import BeautifulSoup

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table,
    TableStyle, HRFlowable
)
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_RIGHT

# ── Config ─────────────────────────────────────────────────────
TARGET_SECTORS = {
    "Technology", "Software", "Semiconductors", "Hardware",
    "Finance", "Financial Services", "Banking", "Insurance",
    "Energy", "Oil & Gas",
    "Healthcare", "Biotechnology", "Pharmaceuticals",
    "Communication Services", "Media"
}

MIN_MARKET_CAP = 20_000_000_000
MIN_PRICE      = 20.0
HIGH_BETA      = 1.5
OUTPUT_PDF     = "rabbit_season.pdf"


# ── Step 1: Get earnings calendar for next week (Mon–Wed) ──────
def get_week_dates():
    today    = datetime.today()
    # Script runs Sunday — get the coming Mon/Tue/Wed
    monday   = today + timedelta(days=1)
    return [monday + timedelta(days=i) for i in range(3)]


def fetch_earnings_calendar(dates):
    tickers_by_day = {}
    headers = {"User-Agent": "Mozilla/5.0"}

    for date in dates:
        date_str = date.strftime("%Y-%m-%d")
        url = f"https://finance.yahoo.com/calendar/earnings?day={date_str}"
        try:
            resp = requests.get(url, headers=headers, timeout=10)
            soup = BeautifulSoup(resp.text, "html.parser")
            tickers = []
            for row in soup.select("tr"):
                cells = row.find_all("td")
                if len(cells) >= 4:
                    ticker    = cells[0].get_text(strip=True)
                    time_info = cells[3].get_text(strip=True).lower()
                    if ticker and any(k in time_info for k in ["after", "amc", "close"]):
                        tickers.append(ticker)
            tickers_by_day[date_str] = tickers
        except Exception as e:
            print(f"Warning: could not fetch calendar for {date_str}: {e}")
            tickers_by_day[date_str] = []

    return tickers_by_day


# ── Step 2: Filter and enrich each ticker ──────────────────────
def get_stock_info(ticker):
    try:
        stock = yf.Ticker(ticker)
        info  = stock.info
        return {
            "ticker":  ticker,
            "name":    info.get("shortName") or info.get("longName", ticker),
            "price":   info.get("currentPrice") or info.get("regularMarketPrice", 0) or 0,
            "mkt_cap": info.get("marketCap", 0) or 0,
            "sector":  info.get("sector", "") or "",
            "beta":    info.get("beta", None),
            "stock":   stock,
        }
    except Exception as e:
        print(f"Warning: could not fetch {ticker}: {e}")
        return None


def passes_filter(data):
    if data is None:
        return False
    if data["mkt_cap"] < MIN_MARKET_CAP:
        return False
    if data["price"] < MIN_PRICE:
        return False
    if not any(s.lower() in data["sector"].lower() for s in TARGET_SECTORS):
        return False
    return True


def calc_historical_earnings_moves(stock, quarters=8):
    try:
        earnings_dates = stock.earnings_dates
        if earnings_dates is None or earnings_dates.empty:
            return None
        hist = stock.history(period="3y", interval="1d")
        if hist.empty:
            return None
        moves = []
        for dt in earnings_dates.index[:quarters]:
            dt_date  = dt.date() if hasattr(dt, "date") else dt
            next_day = dt_date + timedelta(days=1)
            try:
                idx = hist.index.get_indexer([pd.Timestamp(next_day)], method="nearest")[0]
                if idx > 0:
                    move = abs(hist.iloc[idx]["Close"] - hist.iloc[idx-1]["Close"]) \
                           / hist.iloc[idx-1]["Close"] * 100
                    moves.append(move)
            except Exception:
                continue
        return round(np.mean(moves), 1) if moves else None
    except Exception:
        return None


def calc_implied_move(stock, price):
    try:
        expirations = stock.options
        if not expirations:
            return "N/A"
        chain   = stock.option_chain(expirations[0])
        calls   = chain.calls
        puts    = chain.puts
        strikes = calls["strike"].values
        atm     = strikes[np.argmin(np.abs(strikes - price))]
        c_row   = calls[calls["strike"] == atm]
        p_row   = puts[puts["strike"]   == atm]
        if c_row.empty or p_row.empty:
            return "N/A"
        c_mid    = (c_row["bid"].values[0] + c_row["ask"].values[0]) / 2
        p_mid    = (p_row["bid"].values[0] + p_row["ask"].values[0]) / 2
        impl_pct = round((c_mid + p_mid) / price * 100, 1)
        return f"+-{impl_pct}%"
    except Exception:
        return "N/A"


# ── Step 3: Build screener rows ────────────────────────────────
def build_screener(tickers_by_day):
    rows = []
    for date_str, tickers in tickers_by_day.items():
        print(f"Processing {date_str}: {len(tickers)} AMC tickers")
        for ticker in tickers:
            print(f"  -> {ticker}")
            data = get_stock_info(ticker)
            if not passes_filter(data):
                continue
            stock   = data["stock"]
            price   = data["price"]
            beta    = data["beta"]
            hist_mv = calc_historical_earnings_moves(stock)
            impl_mv = calc_implied_move(stock, price)
            rows.append({
                "date":      date_str,
                "ticker":    ticker,
                "name":      data["name"],
                "sector":    data["sector"],
                "price":     price,
                "mkt_cap":   data["mkt_cap"],
                "beta":      beta,
                "hist_move": f"+-{hist_mv}%" if hist_mv else "N/A",
                "impl_move": impl_mv,
                "high_beta": (beta or 0) >= HIGH_BETA,
            })
    return rows


# ── Step 4: Generate PDF ───────────────────────────────────────
def generate_pdf(rows, week_dates, output_path):
    W, H = A4
    PW   = W - 36 * mm

    doc = SimpleDocTemplate(
        output_path, pagesize=A4,
        leftMargin=18*mm, rightMargin=18*mm,
        topMargin=16*mm, bottomMargin=16*mm
    )

    C_BLACK    = colors.HexColor("#1A1A1A")
    C_GRAY     = colors.HexColor("#6B6B6B")
    C_LGRAY    = colors.HexColor("#F4F3EF")
    C_BORDER   = colors.HexColor("#DDDBD2")
    C_RED_BG   = colors.HexColor("#FAECE7")
    C_RED_TXT  = colors.HexColor("#993C1D")
    C_RED      = colors.HexColor("#E24B4A")
    C_EXCL_TXT = colors.HexColor("#5F5E5A")
    C_WHITE    = colors.white

    def S(name, **kw):
        base = dict(fontName="Helvetica", fontSize=9, leading=13,
                    textColor=C_BLACK, spaceAfter=0)
        base.update(kw)
        return ParagraphStyle(name, **base)

    sTitle   = S("title", fontSize=15, fontName="Helvetica-Bold", leading=20, spaceAfter=2)
    sSubtitle= S("sub",   fontSize=8,  textColor=C_GRAY, spaceAfter=8)
    sSection = S("sec",   fontSize=8,  fontName="Helvetica-Bold", textColor=C_GRAY,
                 spaceAfter=4, spaceBefore=10)
    sTH      = S("th",    fontSize=7.5, fontName="Helvetica-Bold", textColor=C_GRAY)
    sTD      = S("td",    fontSize=8,  leading=11)
    sSummTxt = S("st",    fontSize=7.5, textColor=C_GRAY, leading=11)
    sDisc    = S("disc",  fontSize=6.5, textColor=C_EXCL_TXT, leading=9)

    def td(text, style=None):
        return Paragraph(str(text), style or sTD)

    COLS = [PW*0.08, PW*0.20, PW*0.12, PW*0.14,
            PW*0.09, PW*0.09, PW*0.14, PW*0.14]

    BASE_STYLE = [
        ("BACKGROUND",    (0,0), (-1,0), C_LGRAY),
        ("ROWBACKGROUNDS",(0,1), (-1,-1), [C_WHITE, colors.HexColor("#FAFAF8")]),
        ("GRID",          (0,0), (-1,-1), 0.3, C_BORDER),
        ("LEFTPADDING",   (0,0), (-1,-1), 5),
        ("RIGHTPADDING",  (0,0), (-1,-1), 5),
        ("TOPPADDING",    (0,0), (-1,-1), 4),
        ("BOTTOMPADDING", (0,0), (-1,-1), 4),
        ("VALIGN",        (0,0), (-1,-1), "MIDDLE"),
    ]

    def make_header():
        hdrs = ["Ticker","Company","Date / Time","Sector",
                "Price","Beta","Avg Hist Move","Mkt Implied"]
        return [Paragraph(h, sTH) for h in hdrs]

    def risk_bar_table(day_risk):
        bar_rows = []
        for label, pct, col in day_risk:
            bar_w  = int(PW * 0.50)
            filled = int(bar_w * pct / 100)
            lbl = Paragraph(
                f"<b>{label}</b>" if col == C_RED else label,
                ParagraphStyle("bl", fontSize=8,
                    fontName="Helvetica-Bold" if col==C_RED else "Helvetica",
                    textColor=C_RED_TXT if col==C_RED else C_GRAY, leading=11))
            pct_p = Paragraph(
                f"<b>{pct}%</b>" if col==C_RED else f"{pct}%",
                ParagraphStyle("bp", fontSize=8,
                    fontName="Helvetica-Bold" if col==C_RED else "Helvetica",
                    textColor=C_RED if col==C_RED else C_GRAY,
                    alignment=TA_RIGHT, leading=11))
            bar = Table([["",""]], colWidths=[filled, bar_w-filled], rowHeights=[6])
            bar.setStyle(TableStyle([
                ("BACKGROUND",(0,0),(0,0), col),
                ("BACKGROUND",(1,0),(1,0), C_BORDER),
                ("LEFTPADDING",(0,0),(-1,-1),0),("RIGHTPADDING",(0,0),(-1,-1),0),
                ("TOPPADDING",(0,0),(-1,-1),0),("BOTTOMPADDING",(0,0),(-1,-1),0),
                ("GRID",(0,0),(-1,-1),0,C_WHITE),
            ]))
            bar_rows.append([lbl, bar, pct_p])
        t = Table(bar_rows, colWidths=[PW*0.22, PW*0.50, PW*0.12])
        t.setStyle(TableStyle([
            ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
            ("LEFTPADDING",(0,0),(-1,-1),2),("RIGHTPADDING",(0,0),(-1,-1),2),
            ("TOPPADDING",(0,0),(-1,-1),4),("BOTTOMPADDING",(0,0),(-1,-1),4),
        ]))
        return t

    story      = []
    week_start = week_dates[0].strftime("%b %d")
    week_end   = week_dates[2].strftime("%b %d, %Y")

    story.append(Paragraph("Rabbit Season", sTitle))
    story.append(Paragraph(
        f"Earnings Volatility Screener  |  Week of {week_start}-{week_end}  |  "
        f"AMC only  |  Mkt cap >$20B  |  Price >$20  |  "
        f"Generated {datetime.today().strftime('%A %b %d, %Y')}",
        sSubtitle))
    story.append(HRFlowable(width="100%", thickness=0.5, color=C_BORDER, spaceAfter=8))

    rows_by_date = {}
    for r in rows:
        rows_by_date.setdefault(r["date"], []).append(r)

    day_labels = {0: "MONDAY", 1: "TUESDAY", 2: "WEDNESDAY"}
    day_risk   = []

    for i, date in enumerate(week_dates):
        date_str  = date.strftime("%Y-%m-%d")
        day_rows  = rows_by_date.get(date_str, [])
        count     = len(day_rows)
        explosive = any(r["high_beta"] for r in day_rows)
        suffix    = f"-- {count} EXPLOSIVE AMC" if explosive and count else \
                    f"-- {count} AMC qualifying" if count else \
                    "-- 0 AMC qualifying"

        story.append(Paragraph(
            f"{day_labels[i]}  {date.strftime('%b %d').upper()}  {suffix}", sSection))

        tbl_rows = [make_header()]
        for r in day_rows:
            beta_str   = f"{r['beta']:.2f} *" if r["high_beta"] else \
                         (f"{r['beta']:.2f}" if r["beta"] else "N/A")
            ticker_str = f"<b>{r['ticker']}</b>" + (" *" if r["high_beta"] else "")
            row_cells  = [
                Paragraph(ticker_str, ParagraphStyle("tk", fontSize=8,
                    fontName="Helvetica-Bold",
                    textColor=C_RED_TXT if r["high_beta"] else C_BLACK, leading=11)),
                td(r["name"]),
                td(date.strftime("%b %d / AMC")),
                td(r["sector"][:20]),
                td(f"${r['price']:.0f}"),
                Paragraph(beta_str, ParagraphStyle("bt", fontSize=8,
                    textColor=C_RED if r["high_beta"] else C_BLACK,
                    fontName="Helvetica-Bold" if r["high_beta"] else "Helvetica",
                    leading=11)),
                Paragraph(r["hist_move"], ParagraphStyle("hm", fontSize=8,
                    textColor=C_RED_TXT if r["high_beta"] else C_BLACK,
                    fontName="Helvetica-Bold" if r["high_beta"] else "Helvetica",
                    leading=11)),
                td(r["impl_move"]),
            ]
            tbl_rows.append(row_cells)

        if not day_rows:
            tbl_rows.append([
                Paragraph("No qualifying AMC reports found.",
                    ParagraphStyle("none", fontSize=8,
                        textColor=C_EXCL_TXT, leading=11)),
                td(""), td(""), td(""), td(""), td(""), td(""), td("")
            ])

        tbl_style_cmds = list(BASE_STYLE)
        for row_idx, r in enumerate(day_rows, start=1):
            if r["high_beta"]:
                tbl_style_cmds.append(
                    ("BACKGROUND", (0,row_idx), (-1,row_idx), C_RED_BG))
        tbl = Table(tbl_rows, colWidths=COLS)
        tbl.setStyle(TableStyle(tbl_style_cmds))
        story.append(tbl)
        story.append(Spacer(1, 10))

        if day_rows:
            avg_beta   = np.mean([r["beta"] or 1.0 for r in day_rows])
            risk_score = min(int(count * avg_beta * 25), 95)
        else:
            risk_score = 5
        day_risk.append((
            f"{day_labels[i][:3]} {date.strftime('%b %d')}",
            risk_score,
            C_RED if risk_score >= 60 else C_BORDER
        ))

    story.append(HRFlowable(width="100%", thickness=0.5, color=C_BORDER, spaceAfter=8))
    story.append(Paragraph("Explosive Risk Summary by Day",
        S("sh", fontSize=9, fontName="Helvetica-Bold", spaceAfter=6)))
    story.append(risk_bar_table(day_risk))
    story.append(Spacer(1, 8))

    high_beta_names = [r["ticker"] for r in rows if r["high_beta"]]
    if high_beta_names:
        story.append(Paragraph(
            f"<b>High-beta names this week (Beta >{HIGH_BETA}):</b> "
            f"{', '.join(high_beta_names)}  --  "
            f"Priority candidates for long volatility strategies (straddle / strangle).",
            sSummTxt))
    else:
        story.append(Paragraph(
            f"No high-beta (Beta >{HIGH_BETA}) qualifying names found this week.",
            sSummTxt))

    story.append(Spacer(1, 10))
    story.append(HRFlowable(width="100%", thickness=0.3, color=C_BORDER, spaceAfter=4))
    story.append(Paragraph(
        "Rabbit Season is generated automatically every Sunday. "
        "For informational purposes only. Not financial advice. "
        "Options carry significant risk of loss.",
        sDisc))

    doc.build(story)
    print(f"PDF saved: {output_path}")
    return output_path


# ── Main ───────────────────────────────────────────────────────
def run():
    print("=== Rabbit Season — Weekly Earnings Volatility Screener ===")
    dates = get_week_dates()
    print(f"Scanning: {[d.strftime('%a %b %d') for d in dates]}")
    tickers_by_day = fetch_earnings_calendar(dates)
    rows = build_screener(tickers_by_day)
    print(f"\nQualifying AMC names: {len(rows)}")
    pdf_path = generate_pdf(rows, dates, OUTPUT_PDF)
    return pdf_path


if __name__ == "__main__":
    run()

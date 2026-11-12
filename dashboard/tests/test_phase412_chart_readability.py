from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]/"app"/"static"
def test_chart_has_labels_ticks_points_thresholds_and_drilldown():
 js=(ROOT/"activity.js").read_text(encoding="utf-8")
 html=(ROOT/"activity.html").read_text(encoding="utf-8")
 css=(ROOT/"activity.css").read_text(encoding="utf-8")
 for token in ("activity-grid-line", "activity-axis-label", "activity-data-point", "activity-chart-references", "showPoint", "thresholds", "gapThreshold", "smoothPath", "'/api/farm/config'", "spread>86400?stamp(ts):clock(ts)"):
  assert token in js
 assert "Diễn biến theo thời gian" in html
 assert "#activity-charts{grid-template-columns:minmax(0,1fr)!important" in css
 assert "<polyline" not in js

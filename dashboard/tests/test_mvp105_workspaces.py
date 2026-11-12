from pathlib import Path
from fastapi.testclient import TestClient
ROOT=Path(__file__).resolve().parents[1]
S=ROOT/'app'/'static'
def test_no_lab_controls_in_farmer_shell():
    farmer=(S/'farmer.html').read_text()
    assert 'id="home-priority"' in farmer
    assert 'href="/advanced-login?next=/expert"' in farmer
    assert 'href="/lab"' in (S/'expert.html').read_text()
    assert 'Chế độ chuyên gia' in farmer
    assert 'name="scenario"' not in farmer
    assert 'Digital Twin Lab' not in farmer
    assert 'v=mvp11' in farmer
    assert 'class="bottom-nav"' in farmer

def test_distinct_workspaces_have_clear_routes_and_return():
    expert=(S/'expert.html').read_text()
    lab=(S/'lab.html').read_text()
    assert 'crop-config-form' in expert
    assert 'lab-soil-warning' in lab
    assert 'lab-refill' in lab
    assert 'href="/"' in expert and 'href="/"' in lab
    assert 'name="scenario"' not in expert
    assert 'crop-config-form' not in lab

def test_home_priority_requires_online_dry_and_outside_window():
    js=(S/'farmer.js').read_text()
    assert 'function renderHomePriority' in js
    assert 'live.clock_valid' in js
    assert 'live.master_enabled' in js
    assert 'askOneTime(Number(b.dataset.zone))' in js
    assert 'Đang chờ giờ tưới' not in js

def test_server_routes_expert_lab():
    from app.main import app
    client=TestClient(app)
    assert client.get('/technical',follow_redirects=False).headers.get('location')=='/expert'
    assert client.get('/expert',follow_redirects=False).status_code==303
    assert client.post('/api/advanced/login',json={'pin':'1111'}).status_code==200
    assert 'Cấu hình khu vực' in client.get('/expert').text
    assert 'Kịch bản môi trường' in client.get('/lab').text

"""
항공 좌석 조회 스크립트 v2
GitHub Actions에서 실행 → data/flights.json 생성
"""
import json
import os
import re
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta, timezone
import time

KST = timezone(timedelta(hours=9))

TARGET_DATES_ENV = os.environ.get('TARGET_DATES', '').strip()
ADULT_COUNT = int(os.environ.get('ADULT_COUNT', '1'))
CHILD_COUNT = int(os.environ.get('CHILD_COUNT', '0'))
DEP_TIME_FROM = os.environ.get('DEP_TIME_FROM', '0000')  # HHMM
DEP_TIME_TO = os.environ.get('DEP_TIME_TO', '2359')

def default_dates():
    today = datetime.now(KST)
    return [(today + timedelta(days=i)).strftime('%Y%m%d') for i in range(1, 8)]

TARGET_DATES = [d.strip() for d in TARGET_DATES_ENV.split(',') if d.strip()] if TARGET_DATES_ENV else default_dates()

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/html, */*',
    'Accept-Language': 'ko-KR,ko;q=0.9,en-US;q=0.8',
    'Accept-Encoding': 'gzip, deflate, br',
    'Connection': 'keep-alive',
}

def in_time_range(dep_time: str) -> bool:
    """출발시간이 설정 범위 내인지 확인 (HH:MM 형식)"""
    if not dep_time:
        return True
    t = dep_time.replace(':', '')
    return DEP_TIME_FROM <= t <= DEP_TIME_TO

# ── 진에어 ────────────────────────────────────────────────────────
def fetch_jinair(date: str, adults: int = 1, children: int = 0) -> dict:
    session = requests.Session()
    session.headers.update(HEADERS)
    # 먼저 메인 페이지 방문해서 쿠키 획득
    try:
        session.get('https://www.jinair.com/', timeout=10)
    except:
        pass

    url = 'https://www.jinair.com/booking/getAirAvailabilityJson'
    payload = {
        'tripType': 'OW',
        'origin1': 'GMP',
        'destination1': 'CJU',
        'travelDate1': date,
        'adultPaxCount': str(adults),
        'childPaxCount': str(children),
        'infantPaxCount': '0',
        'pointOfPurchase': 'KR',
        'refVal': 'JINAIR',
        'cached': 'true',
        'chgBestFareDate': 'true',
    }
    try:
        r = session.post(url, data=payload, timeout=20,
                        headers={**HEADERS, 'Referer': 'https://www.jinair.com/',
                                 'Origin': 'https://www.jinair.com',
                                 'Content-Type': 'application/x-www-form-urlencoded'})
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        return {'airline': 'jinair', 'name': '진에어', 'date': date, 'error': str(e), 'flights': []}

    flights = []
    trips = (data.get('result') or {}).get('originDestinationInfo', [{}])[0].get('tripInfo', [])

    for trip in trips:
        seg = (trip.get('segmentInfo') or [{}])[0]
        if not seg:
            continue
        dep_info = seg.get('departureInfo', {})
        arr_info = seg.get('arrivalInfo', {})
        flt_info = seg.get('flightIdentifierInfo', {})
        dep_time = (dep_info.get('dateTimeLTC') or '')[:16][11:]
        arr_time = (arr_info.get('dateTimeLTC') or '')[:16][11:]
        flight_no = f"{flt_info.get('carrierCode','')}{flt_info.get('flightNumber','')}"

        if not in_time_range(dep_time):
            continue

        available = False
        seats = 0
        min_price = None

        for av in (trip.get('segmentAvailability') or []):
            if av.get('inventoryStatus') == 'AV' and (av.get('seatAvailablity') or 0) > 0:
                available = True
                seats += av.get('seatAvailablity', 0)

        for pi in (trip.get('pricingInfo') or []):
            for pax in (pi.get('paxPricingInfo') or []):
                if pax.get('paxType') == 'ADULT':
                    price = pax.get('totalAmount')
                    if price and (min_price is None or price < min_price):
                        min_price = price
            for sa in (pi.get('segmentAvailability') or []):
                if sa.get('inventoryStatus') == 'AV':
                    available = True

        booking_url = (
            f"https://www.jinair.com/booking/selectSchedule"
            f"?tripType=OW&origin1=GMP&destination1=CJU&travelDate1={date}"
            f"&adultPaxCount={adults}&childPaxCount={children}&infantPaxCount=0&pointOfPurchase=KR"
        )
        flights.append({
            'flightNo': flight_no, 'depTime': dep_time, 'arrTime': arr_time,
            'available': available, 'seats': seats, 'price': min_price,
            'bookingUrl': booking_url,
        })

    return {'airline': 'jinair', 'name': '진에어', 'date': date, 'flights': flights}


# ── 제주항공 ──────────────────────────────────────────────────────
def fetch_jejuair(date: str, adults: int = 1, children: int = 0) -> dict:
    pax_count = adults + children
    url = (
        f"https://www.jejuair.net/ko/ibe/booking/selectSchedule.do"
        f"?tripType=OW&depAirport=GMP&arrAirport=CJU&depDate={date}"
        f"&paxType=ADT&paxCount={pax_count}"
    )
    session = requests.Session()
    session.headers.update(HEADERS)
    try:
        session.get('https://www.jejuair.net/', timeout=10)
    except:
        pass
    try:
        r = session.get(url, timeout=20)
        r.raise_for_status()
        html = r.text
    except Exception as e:
        return {'airline': 'jejuair', 'name': '제주항공', 'date': date, 'error': str(e), 'flights': []}

    soup = BeautifulSoup(html, 'lxml')
    flights = []

    # 방법 1: 탭 버튼 구조 파싱
    flight_items = soup.find_all(class_=re.compile(r'flight-item|schedule-item|result-item'))

    # 방법 2: 직접 패턴
    tk_nums = soup.find_all(class_=re.compile(r'tk-?num|flight-?num|flt-?no'))
    dep_times = soup.find_all(class_=re.compile(r'dep.?time|depart.?time'))
    arr_times = soup.find_all(class_=re.compile(r'arr.?time|arriv.?time'))
    remaining = soup.find_all(class_=re.compile(r'remaining.?seat|seat.?count|avail.?seat'))
    prices = soup.find_all(class_=re.compile(r'price.?txt|fare.?amount|total.?price'))

    for i, tk in enumerate(tk_nums):
        flight_no = tk.get_text(strip=True)
        if not flight_no or not re.match(r'[A-Z0-9]{2,3}\d+', flight_no):
            continue
        dep = dep_times[i].get_text(strip=True) if i < len(dep_times) else None
        arr = arr_times[i].get_text(strip=True) if i < len(arr_times) else None

        if not in_time_range(dep):
            continue

        seat_text = remaining[i].get_text(strip=True) if i < len(remaining) else '0'
        seat_num = int(re.sub(r'[^0-9]', '', seat_text) or '0')
        price_text = prices[i].get_text(strip=True) if i < len(prices) else None
        price = int(price_text.replace(',', '')) if price_text and price_text.replace(',', '').isdigit() else None

        flights.append({
            'flightNo': flight_no, 'depTime': dep, 'arrTime': arr,
            'available': seat_num > 0, 'seats': seat_num, 'price': price,
            'bookingUrl': url,
        })

    # 방법 3: 인라인 JSON
    if not flights:
        for pattern in [r'scheduleList\s*=\s*(\[[\s\S]*?\]);',
                        r'flightList\s*=\s*(\[[\s\S]*?\]);',
                        r'"flights"\s*:\s*(\[[\s\S]*?\])']:
            m = re.search(pattern, html)
            if m:
                try:
                    for s in json.loads(m.group(1)):
                        dep = s.get('depTime') or s.get('dptTm') or s.get('departureTime')
                        if not in_time_range(dep):
                            continue
                        flights.append({
                            'flightNo': s.get('flightNo') or s.get('fltNo'),
                            'depTime': dep,
                            'arrTime': s.get('arrTime') or s.get('arvTm'),
                            'available': int(s.get('availSeat') or s.get('remainSeat') or 0) > 0,
                            'seats': int(s.get('availSeat') or s.get('remainSeat') or 0),
                            'price': s.get('totalAmt') or s.get('fare'),
                            'bookingUrl': url,
                        })
                    break
                except:
                    pass

    return {'airline': 'jejuair', 'name': '제주항공', 'date': date, 'flights': flights}


# ── 티웨이 ────────────────────────────────────────────────────────
def fetch_tway(date: str, adults: int = 1, children: int = 0) -> dict:
    booking_url = (
        f"https://www.twayair.com/app/booking/chooseItinerary"
        f"?tripType=OW&depAirport=GMP&arrAirport=CJU&depDate={date}"
        f"&paxType=ADT&paxCount={adults}"
    )
    session = requests.Session()
    session.headers.update(HEADERS)
    try:
        session.get('https://www.twayair.com/', timeout=10)
    except:
        pass
    try:
        r = session.get(booking_url, timeout=20)
        r.raise_for_status()
        html = r.text
    except Exception as e:
        return {'airline': 'tway', 'name': '티웨이', 'date': date,
                'error': str(e), 'flights': [], 'fallbackUrl': booking_url}

    soup = BeautifulSoup(html, 'lxml')
    flights = []
    seen = set()

    for box in soup.find_all(attrs={'data-flightnumber': re.compile(r'TW\d+')}):
        flight_no = box.get('data-flightnumber', '')
        if not flight_no or flight_no in seen:
            continue
        seen.add(flight_no)

        dep_el = box.find(class_=re.compile(r'service_name.*first'))
        arr_el = box.find(class_=re.compile(r'service_name.*last'))
        dep = dep_el.find('strong').get_text(strip=True) if dep_el and dep_el.find('strong') else None
        arr = arr_el.find('strong').get_text(strip=True) if arr_el and arr_el.find('strong') else None

        if not in_time_range(dep):
            continue

        price_info = box.find_next(class_=re.compile(r'price_info.*fareInfo')) or box.find_next(class_='price_info')
        seats, price, available = 0, None, False
        if price_info:
            seat_el = price_info.find(class_=re.compile(r'empty_seats'))
            price_el = price_info.find('strong', class_=re.compile(r'price'))
            if seat_el:
                seats = int(re.sub(r'[^0-9]', '', seat_el.get_text(strip=True)) or '0')
                available = seats > 0
            if price_el:
                p = price_el.get_text(strip=True).replace(',', '')
                price = int(p) if p.isdigit() else None

        flights.append({
            'flightNo': flight_no, 'depTime': dep, 'arrTime': arr,
            'available': available, 'seats': seats, 'price': price,
            'bookingUrl': booking_url,
        })

    if not flights:
        return {'airline': 'tway', 'name': '티웨이', 'date': date,
                'flights': [], 'fallbackUrl': booking_url,
                'note': '티웨이는 예매 페이지에서 직접 확인해주세요.'}

    return {'airline': 'tway', 'name': '티웨이', 'date': date, 'flights': flights}


# ── 메인 ─────────────────────────────────────────────────────────
def main():
    os.makedirs('data', exist_ok=True)
    now = datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{now} KST] 조회 시작 — 날짜: {TARGET_DATES}, 성인: {ADULT_COUNT}, 어린이: {CHILD_COUNT}")
    print(f"출발시간 필터: {DEP_TIME_FROM}~{DEP_TIME_TO}")

    results = []
    for date in TARGET_DATES:
        print(f"\n  📅 {date[:4]}-{date[4:6]}-{date[6:]} 조회 중...")
        for fetcher, name in [(fetch_jinair, '진에어'), (fetch_jejuair, '제주항공'), (fetch_tway, '티웨이')]:
            try:
                r = fetcher(date, ADULT_COUNT, CHILD_COUNT)
                avail = len([f for f in r.get('flights', []) if f.get('available')])
                print(f"    ✈️  {name}: {len(r.get('flights',[]))}편 / 잔여 {avail}편")
                results.append(r)
            except Exception as e:
                print(f"    ✈️  {name} 오류: {e}")
            time.sleep(1.5)

    output = {
        'updatedAt': now,
        'targetDates': TARGET_DATES,
        'adultCount': ADULT_COUNT,
        'childCount': CHILD_COUNT,
        'depTimeFrom': DEP_TIME_FROM,
        'depTimeTo': DEP_TIME_TO,
        'results': results,
    }
    with open('data/flights.json', 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    total_avail = sum(len([f for f in r.get('flights', []) if f.get('available')]) for r in results)
    print(f"\n✅ 완료! 전체 잔여석: {total_avail}편")

if __name__ == '__main__':
    main()

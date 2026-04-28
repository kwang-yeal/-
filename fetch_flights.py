"""
항공 좌석 조회 스크립트
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

# ── 설정 ────────────────────────────────────────────────────────────
# GitHub Variables(vars.TARGET_DATES)에 날짜 설정하거나 여기서 직접 설정
TARGET_DATES_ENV = os.environ.get('TARGET_DATES', '').strip()
ADULT_COUNT = int(os.environ.get('ADULT_COUNT', '1'))

# 기본값: 오늘부터 7일간
def default_dates():
    dates = []
    today = datetime.now(KST)
    for i in range(1, 8):
        d = today + timedelta(days=i)
        dates.append(d.strftime('%Y%m%d'))
    return dates

TARGET_DATES = [d.strip() for d in TARGET_DATES_ENV.split(',') if d.strip()] if TARGET_DATES_ENV else default_dates()

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0',
    'Accept': 'application/json, text/html, */*',
    'Accept-Language': 'ko-KR,ko;q=0.9',
}

# ── 진에어 ────────────────────────────────────────────────────────
def fetch_jinair(date: str, adults: int = 1) -> dict:
    url = 'https://www.jinair.com/booking/getAirAvailabilityJson'
    payload = {
        'tripType': 'OW',
        'origin1': 'GMP',
        'destination1': 'CJU',
        'travelDate1': date,
        'adultPaxCount': str(adults),
        'childPaxCount': '0',
        'infantPaxCount': '0',
        'pointOfPurchase': 'KR',
        'refVal': 'JINAIR',
        'cached': 'true',
        'chgBestFareDate': 'true',
    }
    headers = {**HEADERS, 'Referer': 'https://www.jinair.com/'}
    try:
        r = requests.post(url, data=payload, headers=headers, timeout=15)
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

        dep_time = (dep_info.get('dateTimeLTC') or '')[:16][11:]  # HH:MM
        arr_time = (arr_info.get('dateTimeLTC') or '')[:16][11:]
        flight_no = f"{flt_info.get('carrierCode','')}{flt_info.get('flightNumber','')}"

        # 잔여석 / 가격
        avails = trip.get('segmentAvailability') or []
        seats = 0
        available = False
        min_price = None

        for av in avails:
            if av.get('inventoryStatus') == 'AV' and (av.get('seatAvailablity') or 0) > 0:
                available = True
                seats += av.get('seatAvailablity', 0)

        # pricingInfo에서 최저가
        for pi in (trip.get('pricingInfo') or []):
            for pax in (pi.get('paxPricingInfo') or []):
                if pax.get('paxType') == 'ADULT':
                    price = pax.get('totalAmount')
                    if price and (min_price is None or price < min_price):
                        min_price = price
                    # availabilityStatus 확인
                    if pi.get('segmentAvailability'):
                        for sa in pi['segmentAvailability']:
                            if sa.get('inventoryStatus') == 'AV':
                                available = True

        booking_url = (
            f"https://www.jinair.com/booking/selectSchedule"
            f"?tripType=OW&origin1=GMP&destination1=CJU&travelDate1={date}"
            f"&adultPaxCount={adults}&childPaxCount=0&infantPaxCount=0&pointOfPurchase=KR"
        )

        flights.append({
            'flightNo': flight_no,
            'depTime': dep_time,
            'arrTime': arr_time,
            'available': available,
            'seats': seats,
            'price': min_price,
            'bookingUrl': booking_url,
        })

    return {'airline': 'jinair', 'name': '진에어', 'date': date, 'flights': flights}


# ── 제주항공 ──────────────────────────────────────────────────────
def fetch_jejuair(date: str, adults: int = 1) -> dict:
    url = (
        f"https://www.jejuair.net/ko/ibe/booking/selectSchedule.do"
        f"?tripType=OW&depAirport=GMP&arrAirport=CJU&depDate={date}"
        f"&paxType=ADT&paxCount={adults}"
    )
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        r.raise_for_status()
        html = r.text
    except Exception as e:
        return {'airline': 'jejuair', 'name': '제주항공', 'date': date, 'error': str(e), 'flights': []}

    soup = BeautifulSoup(html, 'lxml')
    flights = []
    booking_url = url

    # 편명 블록 찾기
    tk_nums = soup.find_all(class_=re.compile(r'tk-num'))
    dep_times = soup.find_all(class_=re.compile(r'dep_time'))
    arr_times = soup.find_all(class_=re.compile(r'arr_time'))
    remaining = soup.find_all(class_=re.compile(r'remaining-seat'))
    prices_els = soup.find_all(class_=re.compile(r'price_txt'))

    for i, tk in enumerate(tk_nums):
        flight_no = tk.get_text(strip=True)
        if not flight_no:
            continue
        dep = dep_times[i].get_text(strip=True) if i < len(dep_times) else None
        arr = arr_times[i].get_text(strip=True) if i < len(arr_times) else None
        seat_text = remaining[i].get_text(strip=True) if i < len(remaining) else '0'
        seat_num = int(re.sub(r'[^0-9]', '', seat_text) or '0')
        price_text = prices_els[i].get_text(strip=True) if i < len(prices_els) else None
        price = int(price_text.replace(',', '')) if price_text and price_text.replace(',', '').isdigit() else None

        flights.append({
            'flightNo': flight_no,
            'depTime': dep,
            'arrTime': arr,
            'available': seat_num > 0,
            'seats': seat_num,
            'price': price,
            'bookingUrl': booking_url,
        })

    # 파싱 실패 시 JSON 인라인 데이터 시도
    if not flights:
        m = re.search(r'scheduleList\s*=\s*(\[[\s\S]*?\]);', html)
        if m:
            try:
                for s in json.loads(m.group(1)):
                    flights.append({
                        'flightNo': s.get('flightNo') or s.get('fltNo'),
                        'depTime': s.get('depTime') or s.get('dptTm'),
                        'arrTime': s.get('arrTime') or s.get('arvTm'),
                        'available': int(s.get('availSeat') or s.get('remainSeat') or 0) > 0,
                        'seats': int(s.get('availSeat') or s.get('remainSeat') or 0),
                        'price': s.get('totalAmt') or s.get('fare'),
                        'bookingUrl': booking_url,
                    })
            except Exception:
                pass

    return {'airline': 'jejuair', 'name': '제주항공', 'date': date, 'flights': flights}


# ── 티웨이 ────────────────────────────────────────────────────────
def fetch_tway(date: str, adults: int = 1) -> dict:
    booking_url = (
        f"https://www.twayair.com/app/booking/chooseItinerary"
        f"?tripType=OW&depAirport=GMP&arrAirport=CJU&depDate={date}"
        f"&paxType=ADT&paxCount={adults}"
    )
    try:
        r = requests.get(booking_url, headers=HEADERS, timeout=20)
        r.raise_for_status()
        html = r.text
    except Exception as e:
        return {
            'airline': 'tway', 'name': '티웨이', 'date': date,
            'error': str(e), 'flights': [], 'fallbackUrl': booking_url
        }

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

        # 잔여석과 가격은 price_info fareInfo에서
        price_info = box.find_next(class_=re.compile(r'price_info.*fareInfo')) or box.find_next(class_='price_info')
        seats = 0
        price = None
        available = False

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
            'flightNo': flight_no,
            'depTime': dep,
            'arrTime': arr,
            'available': available,
            'seats': seats,
            'price': price,
            'bookingUrl': booking_url,
        })

    # 서버사이드 렌더링 안 된 경우
    if not flights:
        return {
            'airline': 'tway', 'name': '티웨이', 'date': date,
            'flights': [], 'fallbackUrl': booking_url,
            'note': '티웨이는 예매 페이지에서 직접 확인해주세요.'
        }

    return {'airline': 'tway', 'name': '티웨이', 'date': date, 'flights': flights}


# ── 메인 ─────────────────────────────────────────────────────────
def main():
    os.makedirs('data', exist_ok=True)

    now = datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{now} KST] 조회 시작 — 날짜: {TARGET_DATES}, 성인: {ADULT_COUNT}명")

    results = []
    for date in TARGET_DATES:
        print(f"\n  📅 {date[:4]}-{date[4:6]}-{date[6:]} 조회 중...")

        # 진에어
        try:
            r = fetch_jinair(date, ADULT_COUNT)
            avail = [f for f in r['flights'] if f['available']]
            print(f"    ✈️  진에어: {len(r['flights'])}편 / 잔여 {len(avail)}편")
            results.append(r)
        except Exception as e:
            print(f"    ✈️  진에어 오류: {e}")
        time.sleep(1)

        # 제주항공
        try:
            r = fetch_jejuair(date, ADULT_COUNT)
            avail = [f for f in r['flights'] if f['available']]
            print(f"    ✈️  제주항공: {len(r['flights'])}편 / 잔여 {len(avail)}편")
            results.append(r)
        except Exception as e:
            print(f"    ✈️  제주항공 오류: {e}")
        time.sleep(1)

        # 티웨이
        try:
            r = fetch_tway(date, ADULT_COUNT)
            avail = [f for f in r['flights'] if f['available']]
            print(f"    ✈️  티웨이: {len(r['flights'])}편 / 잔여 {len(avail)}편")
            results.append(r)
        except Exception as e:
            print(f"    ✈️  티웨이 오류: {e}")
        time.sleep(1)

    output = {
        'updatedAt': now,
        'targetDates': TARGET_DATES,
        'adultCount': ADULT_COUNT,
        'results': results,
    }

    with open('data/flights.json', 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n✅ data/flights.json 저장 완료")

    # 요약 출력
    total_avail = sum(
        len([f for f in r.get('flights', []) if f.get('available')])
        for r in results
    )
    print(f"📊 전체 잔여석 편수: {total_avail}")


if __name__ == '__main__':
    main()

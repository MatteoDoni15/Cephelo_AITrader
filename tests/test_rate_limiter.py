from aitrade.rate_limiter import Bucket, RateLimiter


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.slept = 0.0

    def clock(self):
        return self.now

    def sleep(self, s):
        self.now += s
        self.slept += s


def test_bucket_enforces_min_interval():
    fc = FakeClock()
    b = Bucket(5.0, clock=fc.clock, sleeper=fc.sleep)
    b.acquire()                 # subito
    assert fc.slept == 0.0
    b.acquire()                 # deve attendere 5s
    assert fc.slept == 5.0
    b.acquire()
    assert fc.slept == 10.0


def test_order_bucket_is_5_seconds():
    fc = FakeClock()
    rl = RateLimiter(clock=fc.clock, sleeper=fc.sleep)
    rl.acquire(RateLimiter.ORDER_WRITE)
    rl.acquire(RateLimiter.ORDER_WRITE)
    assert fc.slept >= 5.0


def test_market_info_bucket_3_per_10s():
    fc = FakeClock()
    rl = RateLimiter(clock=fc.clock, sleeper=fc.sleep)
    for _ in range(4):
        rl.acquire(RateLimiter.MARKET_INFO)
    # 4 richieste a ~3.33s di distanza -> almeno 10s totali
    assert fc.slept >= 10.0 - 1e-9

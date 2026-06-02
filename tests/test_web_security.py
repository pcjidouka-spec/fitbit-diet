from diet.web.security import is_loopback_host, host_header_ok, origin_ok


def test_is_loopback_host():
    assert is_loopback_host("127.0.0.1")
    assert is_loopback_host("::1")
    assert is_loopback_host("localhost")
    assert not is_loopback_host("192.168.1.5")
    assert not is_loopback_host("0.0.0.0")


def test_host_header_ok():
    assert host_header_ok("127.0.0.1:8770", 8770)
    assert host_header_ok("localhost:8770", 8770)
    assert not host_header_ok("evil.com:8770", 8770)
    assert not host_header_ok("127.0.0.1:9999", 8770)  # wrong port


def test_origin_ok():
    assert origin_ok("http://127.0.0.1:8770", 8770)
    assert origin_ok("http://localhost:8770", 8770)
    assert not origin_ok("http://evil.com", 8770)
    assert not origin_ok(None, 8770)  # missing Origin on mutation -> reject


def test_malformed_ipv6_port_does_not_raise():
    """`[::1]:abc` のような不正ポートは例外でなく拒否（500 でなく 400/403 経路）。"""
    assert not host_header_ok("[::1]:abc", 8770)
    assert not origin_ok("http://[::1]:abc", 8770)
    # 正当な IPv6 + ポートは通る。
    assert host_header_ok("[::1]:8770", 8770)


def test_oversized_and_out_of_range_ports_rejected():
    """isdigit() を通る巨大/範囲外ポートでも int() 例外を出さず拒否する。"""
    huge = "1" * 5000  # int() の文字列変換上限を超える数字列
    assert not host_header_ok(f"127.0.0.1:{huge}", 8770)
    assert not origin_ok(f"http://127.0.0.1:{huge}", 8770)
    assert not host_header_ok("127.0.0.1:99999", 8770)  # 範囲外 (>65535)

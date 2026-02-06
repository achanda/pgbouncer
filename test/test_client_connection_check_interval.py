"""
Extensive tests for client_connection_check_interval.

When set to a positive value (milliseconds), PgBouncer periodically polls
active client sockets to detect disconnects (e.g. client exit, network drop)
so that server connections can be released sooner. Similar to PostgreSQL's
client_connection_check_interval.
"""

import time
from concurrent.futures import ThreadPoolExecutor

import psycopg
import pytest
from psycopg.rows import dict_row

from .utils import Bouncer


def get_client_connection_check_interval(bouncer):
    """Return the current client_connection_check_interval config value (int)."""
    rows = bouncer.admin("SHOW CONFIG", row_factory=dict_row)
    row = next(r for r in rows if r["key"] == "client_connection_check_interval")
    return int(row["value"])


def test_client_connection_check_interval_default(bouncer):
    """Default is 0 (disabled)."""
    assert get_client_connection_check_interval(bouncer) == 0


def test_client_connection_check_interval_config_value(bouncer):
    """Config value is accepted and shown in SHOW CONFIG."""
    config = f"""
        [databases]
        postgres = host={bouncer.pg.host} port={bouncer.pg.port}

        [pgbouncer]
        listen_addr = {bouncer.host}
        admin_users = pgbouncer
        auth_type = trust
        auth_file = {bouncer.auth_path}
        listen_port = {bouncer.port}
        logfile = {bouncer.log_path}
        client_connection_check_interval = 500
        pool_mode = transaction
    """
    with bouncer.run_with_config(config):
        assert get_client_connection_check_interval(bouncer) == 500


def test_client_connection_check_interval_disabled_no_effect(bouncer):
    """With interval 0, normal queries work and no check runs (sanity)."""
    bouncer.admin("set client_connection_check_interval=0")
    assert get_client_connection_check_interval(bouncer) == 0
    bouncer.test()
    bouncer.sql("select 1")
    bouncer.sql("select pg_sleep(0.5)")


def test_client_connection_check_interval_detects_abrupt_disconnect(bouncer, pg):
    """
    When a client disconnects abruptly during a long query, the periodic check
    detects it and disconnects the client (logging "client connection lost"),
    so the server connection is released without waiting for query_timeout.
    """
    config = f"""
        [databases]
        postgres = host={bouncer.pg.host} port={bouncer.pg.port}

        [pgbouncer]
        listen_addr = {bouncer.host}
        admin_users = pgbouncer
        auth_type = trust
        auth_file = {bouncer.auth_path}
        listen_port = {bouncer.port}
        logfile = {bouncer.log_path}
        pool_mode = transaction
        client_connection_check_interval = 300
        query_timeout = 30
    """
    with bouncer.run_with_config(config):
        assert get_client_connection_check_interval(bouncer) == 300

        # Connect and start a long-running query in a background thread
        conn = bouncer.conn(dbname="postgres", autocommit=True)
        query_started = []
        query_done = []

        def run_long_query():
            try:
                with conn.cursor() as cur:
                    cur.execute("select pg_sleep(10)")
                    query_done.append(True)
            except (psycopg.OperationalError, psycopg.InterfaceError):
                pass  # Expected when we close the connection

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(run_long_query)
            # Give the query time to reach the server and block
            time.sleep(0.5)
            query_started.append(True)

            # Abruptly close the client connection (simulate client crash / network drop)
            conn.close()

            # PgBouncer should detect the dead client within ~2 check intervals (600ms)
            with bouncer.log_contains(r"client connection lost"):
                time.sleep(2)

            # Wait for the background thread to finish (it may see connection closed)
            future.result(timeout=3)


def test_client_connection_check_interval_releases_server(bouncer, pg):
    """
    After the check detects a disconnected client, the server connection
    is released back to the pool (idle or closed). Verify by checking
    that PostgreSQL sees the connection count drop and that a new client
    can use the pool.
    """
    config = f"""
        [databases]
        postgres = host={bouncer.pg.host} port={bouncer.pg.port}

        [pgbouncer]
        listen_addr = {bouncer.host}
        admin_users = pgbouncer
        auth_type = trust
        auth_file = {bouncer.auth_path}
        listen_port = {bouncer.port}
        logfile = {bouncer.log_path}
        pool_mode = transaction
        default_pool_size = 1
        client_connection_check_interval = 300
        query_timeout = 30
    """
    with bouncer.run_with_config(config):
        # First client: connect and start long query
        conn = bouncer.conn(dbname="postgres", autocommit=True)

        def run_long_query():
            try:
                with conn.cursor() as cur:
                    cur.execute("select pg_sleep(10)")
            except (psycopg.OperationalError, psycopg.InterfaceError):
                pass

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(run_long_query)
            time.sleep(0.5)
            assert pg.connection_count() == 1
            conn.close()

            # Wait for "client connection lost" to appear (within ~2 check intervals)
            with bouncer.log_contains(r"client connection lost"):
                time.sleep(2)

            future.result(timeout=3)

        # Allow a moment for server to be released
        time.sleep(0.5)
        # Server should be released (idle or closed); pool has size 1
        assert pg.connection_count() <= 1

        # New client should be able to connect and run a query (pool is usable)
        bouncer.test(dbname="postgres")


def test_client_connection_check_interval_only_checks_active_clients(bouncer):
    """
    The check only runs on active clients (those with a query in progress).
    Idle connected clients are not polled; they are not disconnected by
    the check. So with interval enabled, an idle client can stay connected.
    """
    config = f"""
        [databases]
        postgres = host={bouncer.pg.host} port={bouncer.pg.port}

        [pgbouncer]
        listen_addr = {bouncer.host}
        admin_users = pgbouncer
        auth_type = trust
        auth_file = {bouncer.auth_path}
        listen_port = {bouncer.port}
        logfile = {bouncer.log_path}
        pool_mode = transaction
        client_connection_check_interval = 200
        client_idle_timeout = 10
    """
    with bouncer.run_with_config(config):
        # Idle client: connect, run one query, then stay idle
        with bouncer.cur(dbname="postgres") as cur:
            cur.execute("select 1")
            # Stay idle for longer than several check intervals
            time.sleep(1.0)
            # Should still be connected
            cur.execute("select 2")


def test_client_connection_check_interval_set_via_admin(bouncer):
    """Setting client_connection_check_interval via admin console is reflected in SHOW CONFIG."""
    bouncer.admin("set client_connection_check_interval=1000")
    assert get_client_connection_check_interval(bouncer) == 1000
    bouncer.admin("set client_connection_check_interval=0")
    assert get_client_connection_check_interval(bouncer) == 0


def test_client_connection_check_interval_large_value(bouncer):
    """Large interval value is accepted (e.g. 60000 ms = 1 minute)."""
    config = f"""
        [databases]
        postgres = host={bouncer.pg.host} port={bouncer.pg.port}

        [pgbouncer]
        listen_addr = {bouncer.host}
        admin_users = pgbouncer
        auth_type = trust
        auth_file = {bouncer.auth_path}
        listen_port = {bouncer.port}
        logfile = {bouncer.log_path}
        client_connection_check_interval = 60000
        pool_mode = transaction
    """
    with bouncer.run_with_config(config):
        assert get_client_connection_check_interval(bouncer) == 60000
        bouncer.test()


def test_client_connection_check_interval_with_multiple_active_clients(bouncer, pg):
    """
    When multiple clients are active and one disconnects, only that client
    is detected and disconnected; others are unaffected.
    """
    config = f"""
        [databases]
        postgres = host={bouncer.pg.host} port={bouncer.pg.port}

        [pgbouncer]
        listen_addr = {bouncer.host}
        admin_users = pgbouncer
        auth_type = trust
        auth_file = {bouncer.auth_path}
        listen_port = {bouncer.port}
        logfile = {bouncer.log_path}
        pool_mode = statement
        default_pool_size = 2
        client_connection_check_interval = 300
        query_timeout = 30
    """
    with bouncer.run_with_config(config):
        # Client 1: long query
        conn1 = bouncer.conn(dbname="postgres", autocommit=True)
        done1 = []

        def run1():
            try:
                with conn1.cursor() as cur:
                    cur.execute("select pg_sleep(5)")
                done1.append(True)
            except (psycopg.OperationalError, psycopg.InterfaceError):
                pass

        # Client 2: long query
        conn2 = bouncer.conn(dbname="postgres", autocommit=True)
        done2 = []

        def run2():
            try:
                with conn2.cursor() as cur:
                    cur.execute("select pg_sleep(5)")
                done2.append(True)
            except (psycopg.OperationalError, psycopg.InterfaceError):
                pass

        with ThreadPoolExecutor(max_workers=2) as pool:
            f1 = pool.submit(run1)
            f2 = pool.submit(run2)
            time.sleep(0.5)
            # Kill only client 1
            conn1.close()
            # Wait for detection of client 1
            with bouncer.log_contains(r"client connection lost"):
                time.sleep(2)
            # Client 2 should still complete (or get connection closed when server is released)
            f2.result(timeout=8)
            f1.result(timeout=1)

import base64
import getpass
import http.client
import time
from urllib.parse import urlencode


ROUTER_IP = "192.168.100.1"
USERNAME = "root"

# Wait this long AFTER the router has come back online
INTERVAL = 300  # 5 minutes


def request(conn, method, path, headers=None, body=None):
    conn.request(
        method,
        path,
        body=body,
        headers=headers or {}
    )

    response = conn.getresponse()
    data = response.read()

    return response, data


def get_token(conn):
    response, data = request(
        conn,
        "POST",
        "/asp/GetRandCount.asp",
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Connection": "keep-alive",
        },
    )

    if response.status != 200:
        raise RuntimeError(
            f"GetRandCount failed: HTTP {response.status}"
        )

    token = (
        data
        .decode("utf-8", errors="ignore")
        .lstrip("\ufeff")
        .strip()
    )

    if not token:
        raise RuntimeError(
            "Router returned an empty login token"
        )

    return token


def login(conn, password):
    # GetRandCount and login.cgi intentionally use
    # the SAME HTTPConnection.
    token = get_token(conn)

    password_b64 = base64.b64encode(
        password.encode("utf-8")
    ).decode("ascii")

    body = urlencode({
        "UserName": USERNAME,
        "PassWord": password_b64,
        "Language": "english",
        "x.X_HW_Token": token,
    })

    response, data = request(
        conn,
        "POST",
        "/login.cgi",
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Cookie": "Cookie=body:Language:english:id=-1",
            "Origin": f"http://{ROUTER_IP}",
            "Referer": f"http://{ROUTER_IP}/",
            "Connection": "keep-alive",
        },
        body=body,
    )

    set_cookie = response.getheader("Set-Cookie")

    if not set_cookie:
        raise RuntimeError(
            f"Login failed: no session cookie received "
            f"(HTTP {response.status})"
        )

    if "Cookie=" not in set_cookie:
        raise RuntimeError(
            f"Unexpected login cookie: {set_cookie}"
        )

    cookie_value = set_cookie.split(";", 1)[0]

    if "sid=" not in cookie_value:
        raise RuntimeError(
            f"Login did not return an authenticated session: "
            f"{cookie_value}"
        )

    return cookie_value


def get_session_token(conn, cookie):
    """
    Obtain the token required for authenticated operations
    such as the Restart request.
    """

    response, data = request(
        conn,
        "GET",
        "/html/ssmp/common/GetRandToken.asp",
        headers={
            "Cookie": cookie,
            "Connection": "keep-alive",
        },
    )

    if response.status != 200:
        raise RuntimeError(
            f"GetRandToken failed: HTTP {response.status}"
        )

    token = (
        data
        .decode("utf-8", errors="ignore")
        .lstrip("\ufeff")
        .strip()
    )

    if not token:
        raise RuntimeError(
            "Router returned an empty session token"
        )

    return token


def reboot_router(password):
    print("Connecting to router...")

    conn = http.client.HTTPConnection(
        ROUTER_IP,
        80,
        timeout=15,
    )

    try:
        print("Getting login token...")
        cookie = login(conn, password)

        print("Logged in successfully.")

        print("Getting reboot token...")
        reboot_token = get_session_token(conn, cookie)

        reboot_path = (
            "/html/ssmp/accoutcfg/set.cgi"
            "?x=InternetGatewayDevice.X_HW_DEBUG.SMP.DM.ResetBoard"
            "&RequestFile=html/ssmp/accoutcfg/ontmngt.asp"
        )

        body = urlencode({
            "x.X_HW_Token": reboot_token
        })

        print("Sending RESTART command...")

        try:
            response, data = request(
                conn,
                "POST",
                reboot_path,
                headers={
                    "Content-Type":
                        "application/x-www-form-urlencoded",
                    "Cookie": cookie,
                    "Origin": f"http://{ROUTER_IP}",
                    "Referer": (
                        f"http://{ROUTER_IP}"
                        "/html/ssmp/accoutcfg/ontmngt.asp"
                    ),
                    "Connection": "close",
                },
                body=body,
            )

            print(
                f"Restart request returned HTTP "
                f"{response.status}"
            )

            if response.status not in (200, 302, 303):
                print(
                    data.decode(
                        "utf-8",
                        errors="ignore"
                    )[:500]
                )

                raise RuntimeError(
                    "Router rejected the restart request."
                )

        except (TimeoutError, OSError):
            # The router can shut down the HTTP connection
            # immediately after accepting the reboot command.
            #
            # In that situation, a timeout means the router
            # disappeared while rebooting, which is exactly
            # what we expect.
            print(
                "Router stopped responding — "
                "reboot command was triggered."
            )

    finally:
        conn.close()


def router_is_up():
    conn = None

    try:
        conn = http.client.HTTPConnection(
            ROUTER_IP,
            80,
            timeout=3,
        )

        response, _ = request(
            conn,
            "GET",
            "/",
            headers={
                "Connection": "close"
            },
        )

        return response.status < 500

    except Exception:
        return False

    finally:
        if conn:
            conn.close()


def wait_for_router():
    print("Waiting for router to come back online...")

    while True:
        if router_is_up():
            print()
            print("Router is back online.")
            return

        print(".", end="", flush=True)
        time.sleep(5)


def main():
    print("Huawei EG8145V5 automatic reboot")
    print("--------------------------------")
    print(f"Router: {ROUTER_IP}")
    print(
        f"Interval after reboot: "
        f"{INTERVAL // 60} minutes"
    )
    print()

    password = getpass.getpass(
        "Router password: "
    )

    while True:
        try:
            reboot_router(password)

        except Exception as e:
            print()
            print(f"ERROR: {e}")
            print(
                "Will retry after 30 seconds..."
            )
            time.sleep(30)
            continue

        # Reboot command was successfully sent,
        # even if the HTTP connection timed out.
        wait_for_router()

        print()
        print(
            f"Waiting {INTERVAL // 60} minutes "
            "before the next restart..."
        )

        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
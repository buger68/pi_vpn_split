import socket
import struct
import threading
import time
import dns.resolver
import dns.message
import dns.query
import dns.rdatatype
import dns.flags
from config import DNS_HOST, DNS_PORT, UPSTREAM_DNS, UPSTREAM_DOH_URL, REFRESH_INTERVAL, VPN_INTERFACE
from domain_store import DomainStore

class DNSServer:
    """DNS-сервер, который перехватывает запросы к управляемым доменам"""

    def __init__(self, domain_store: DomainStore, route_manager):
        self.store = domain_store
        self.route_manager = route_manager
        self.resolver = dns.resolver.Resolver()
        self.resolver.nameservers = [UPSTREAM_DNS]

    def _resolve_via_doh(self, request: dns.message.Message) -> dns.message.Message:
        """Разрешить DNS-запрос через DoH (шифрованный)"""
        try:
            response = dns.query.https(request, UPSTREAM_DOH_URL, timeout=10)
            return response
        except Exception as e:
            print(f"[DNS] DoH ошибка, fallback к UDP: {e}")
            try:
                response = dns.query.udp(request, UPSTREAM_DNS, timeout=5)
                return response
            except Exception as e2:
                print(f"[DNS] UDP fallback ошибка: {e2}")
                raise

    def _resolve_a_via_doh(self, qname: str):
        """Разрешить A-запись домена через DoH, вернуть список (ip, ttl)"""
        try:
            answers = self.resolver.resolve(qname, "A")
            results = []
            for rdata in answers:
                results.append((str(rdata), answers.rrset.ttl if answers.rrset else 300))
            return results
        except Exception as e:
            print(f"[DNS] Ошибка resolve {qname}: {e}")
            return []

    def refresh_domains_loop(self):
        """Фоновый поток для периодического ре-резолвинга управляемых доменов"""
        print(f"[DNS] Поток ре-резолвинга запущен (интервал: {REFRESH_INTERVAL}с)")
        while True:
            time.sleep(REFRESH_INTERVAL)
            try:
                self._refresh_all_managed()
            except Exception as e:
                print(f"[DNS] Ошибка в цикле ре-резолвинга: {e}")

    def _resolve_domain_subnames(self, domain: str) -> list:
        """Для wildcard-домена резолвит несколько поддоменов, чтобы собрать больше IP"""
        if domain.startswith("*."):
            base = domain[2:]  # убираем *.
            subdomains = [
                "www." + base,
                base,
                "m." + base,
                "music." + base,
                "tv." + base,
                "video." + base,
                "api." + base,
                "cdn." + base,
            ]
        else:
            subdomains = [domain]

        all_results = {}  # ip -> ttl
        for sub in subdomains:
            try:
                results = self._resolve_a_via_doh(sub)
                for ip, ttl in results:
                    if ip not in all_results or ttl > all_results[ip]:
                        all_results[ip] = ttl
            except Exception:
                pass
        return [(ip, ttl) for ip, ttl in all_results.items()]

    def _refresh_all_managed(self):
        """Пере-резолвить все управляемые домены, обновить маршруты"""
        domains = self.store.list_domains()
        if not domains:
            return

        print(f"[DNS] Ре-резолвинг {len(domains)} доменов...")
        for domain in domains:
            try:
                old_ips = set(self.store.get_domain_ips(domain))
                new_ips_with_ttl = self._resolve_domain_subnames(domain)
                new_ips = set(ip for ip, ttl in new_ips_with_ttl)

                if not new_ips:
                    continue

                added_ips = new_ips - old_ips
                for ip, ttl in new_ips_with_ttl:
                    if ip in added_ips:
                        print(f"[DNS] Новый IP {ip} для {domain} (TTL: {ttl}с)")
                        self.store.add_ip_for_domain(domain, ip, ttl)
                        self.route_manager.add_route(ip)
                        self.store.mark_route_added(domain, ip)
                    elif ip in old_ips:
                        self.store.update_ip_ttl(domain, ip, ttl)

            except Exception as e:
                print(f"[DNS] Ошибка ре-резолвинга {domain}: {e}")

        print(f"[DNS] Ре-резолвинг завершён")

    def start(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((DNS_HOST, DNS_PORT))
        print(f"[DNS] Сервер запущен на {DNS_HOST}:{DNS_PORT}")
        print(f"[DNS] Upstream: {UPSTREAM_DOH_URL} (DoH), fallback: {UPSTREAM_DNS} (UDP)")

        # Запускаем фоновый поток ре-резолвинга
        refresh_thread = threading.Thread(target=self.refresh_domains_loop, daemon=True)
        refresh_thread.start()

        while True:
            data, addr = sock.recvfrom(1024)
            threading.Thread(target=self.handle_query, args=(sock, data, addr), daemon=True).start()

    def handle_query(self, sock, data, addr):
        try:
            request = dns.message.from_wire(data)
            response = dns.message.make_response(request)

            if len(request.question) == 0:
                return

            qname = str(request.question[0].name).rstrip(".")
            qtype = request.question[0].rdtype

            print(f"[DNS] Запрос: {qname} (тип {qtype})")

            # Нас интересуют только A-записи (IPv4)
            if qtype != dns.rdatatype.A:
                # Прокси запрос через DoH
                try:
                    upstream_resp = self._resolve_via_doh(request)
                    sock.sendto(upstream_resp.to_wire(), addr)
                except Exception as e:
                    print(f"[DNS] Ошибка upstream для {qname}: {e}")
                return

            if self.store.is_managed(qname):
                # Управляемый домен — резолвим через DoH, но перехватываем IP
                try:
                    answers = self.resolver.resolve(qname, "A")
                    for rdata in answers:
                        ip = str(rdata)
                        ttl = answers.rrset.ttl if answers.rrset else 300
                        print(f"[DNS] Управляемый домен {qname} -> {ip} (TTL: {ttl}с)")
                        self.store.add_ip_for_domain(qname, ip, ttl)
                        # Добавляем маршрут через VPN
                        self.route_manager.add_route(ip)
                        self.store.mark_route_added(qname, ip)
                        # Добавляем A-запись в ответ
                        rrset = dns.rrset.RRset(
                            name=dns.name.from_text(qname + "."),
                            rdclass=dns.rdataclass.IN,
                            rdtype=dns.rdatatype.A
                        )
                        rrset.add(dns.rdtypes.IN.A.A(rdclass=dns.rdataclass.IN, rdtype=dns.rdatatype.A, address=ip))
                        response.answer.append(rrset)
                except Exception as e:
                    print(f"[DNS] Не удалось резолвить {qname}: {e}")
                    response.flags |= dns.flags.QR | dns.flags.RA | dns.flags.NXDOMAIN
            else:
                # Неуправляемый домен — прокси через DoH
                try:
                    upstream_resp = self._resolve_via_doh(request)
                    sock.sendto(upstream_resp.to_wire(), addr)
                    return
                except Exception as e:
                    print(f"[DNS] Ошибка upstream для {qname}: {e}")
                    response.flags |= dns.flags.QR | dns.flags.RA | dns.flags.SERVFAIL

            sock.sendto(response.to_wire(), addr)
        except Exception as e:
            print(f"[DNS] Ошибка обработки запроса: {e}")
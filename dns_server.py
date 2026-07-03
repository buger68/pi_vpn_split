import socket
import struct
import threading
import dns.resolver
import dns.message
import dns.query
import dns.rdatatype
import dns.flags
from config import DNS_HOST, DNS_PORT, UPSTREAM_DNS, VPN_INTERFACE
from domain_store import DomainStore

class DNSServer:
    """DNS-сервер, который перехватывает запросы к управляемым доменам"""

    def __init__(self, domain_store: DomainStore, route_manager):
        self.store = domain_store
        self.route_manager = route_manager
        self.resolver = dns.resolver.Resolver()
        self.resolver.nameservers = [UPSTREAM_DNS]

    def start(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((DNS_HOST, DNS_PORT))
        print(f"[DNS] Сервер запущен на {DNS_HOST}:{DNS_PORT}")
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
                # Прокси запрос к upstream
                try:
                    upstream_resp = dns.query.udp(request, UPSTREAM_DNS, timeout=5)
                    sock.sendto(upstream_resp.to_wire(), addr)
                except Exception as e:
                    print(f"[DNS] Ошибка upstream для {qname}: {e}")
                return

            if self.store.is_managed(qname):
                # Управляемый домен — резолвим через upstream, но перехватываем IP
                try:
                    answers = self.resolver.resolve(qname, "A")
                    for rdata in answers:
                        ip = str(rdata)
                        print(f"[DNS] Управляемый домен {qname} -> {ip}")
                        self.store.add_ip_for_domain(qname, ip)
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
                # Неуправляемый домен — прокси к upstream
                try:
                    upstream_resp = dns.query.udp(request, UPSTREAM_DNS, timeout=5)
                    sock.sendto(upstream_resp.to_wire(), addr)
                    return
                except Exception as e:
                    print(f"[DNS] Ошибка upstream для {qname}: {e}")
                    response.flags |= dns.flags.QR | dns.flags.RA | dns.flags.SERVFAIL

            sock.sendto(response.to_wire(), addr)
        except Exception as e:
            print(f"[DNS] Ошибка обработки запроса: {e}")

# coding=utf-8
import socket
import threading
import json
import uuid
import os
import time
from datetime import datetime

CHAT_PORT = 12345
DISCOVERY_PORT = 12346
BUFFER_SIZE = 1024

USER_FILE = 'user_data.json'

def load_user_data():
    if os.path.exists(USER_FILE):
        try:
            with open(USER_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except json.JSONDecodeError:
            print("Erro: Arquivo de dados do usuário corrompido. Será criado um novo.")
            os.remove(USER_FILE)
            return None
        except Exception as e:
            print(f"Erro ao carregar dados do usuário: {e}")
            return None
    return None

def save_user_data(user_id, user_name):
    try:
        with open(USER_FILE, 'w', encoding='utf-8') as f:
            json.dump({'id': user_id, 'name': user_name}, f)
    except Exception as e:
        print(f"Erro ao salvar dados do usuário: {e}")

MY_ID = None
MY_NAME = None

CONTACTS = {}

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip_address = s.getsockname()[0]
        s.close()
        return ip_address
    except Exception as e:
        print(f"Erro ao obter IP local: {e}. Verifique sua conexão Wi-Fi.")
        return "127.0.0.1"

def get_broadcast_ip(local_ip):
    if local_ip == "127.0.0.1":
        return "255.255.255.255"
    parts = local_ip.split('.')
    return f"{parts[0]}.{parts[1]}.{parts[2]}.255"

class ChatServer:
    def __init__(self, host_ip, chat_port, discovery_port):
        self.host_ip = host_ip
        self.chat_port = chat_port
        self.discovery_port = discovery_port
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.clients = {}
        self.client_names = {}
        self.running = True
        self.broadcast_socket = None

    def start(self):
        try:
            self.server_socket.bind((self.host_ip, self.chat_port))
            self.server_socket.listen(5)
            print(f"\n--- Servidor de Chat Iniciado em {self.host_ip}:{self.chat_port} ---")
            print("Aguardando conexões de amigos na mesma rede Wi-Fi...")
            print(f"Seu código de chat (compartilhe com amigos): {MY_ID}")

            accept_thread = threading.Thread(target=self._accept_connections)
            accept_thread.daemon = True
            accept_thread.start()

            broadcast_thread = threading.Thread(target=self._start_udp_broadcasting)
            broadcast_thread.daemon = True
            broadcast_thread.start()

            threading.Thread(target=self._handle_user_input).start()

        except OSError as e:
            if e.errno == 98:
                print(f"\nErro: A porta {self.chat_port} já está em uso ou o servidor já está rodando. Tente novamente mais tarde ou reinicie.")
            else:
                print(f"\nErro ao iniciar o servidor: {e}")
            self.running = False

    def _start_udp_broadcasting(self):
        self.broadcast_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.broadcast_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self.broadcast_socket.settimeout(0.5)

        broadcast_ip = get_broadcast_ip(self.host_ip)

        print(f"Iniciando broadcast de descoberta em {broadcast_ip}:{self.discovery_port}")

        while self.running:
            try:
                discovery_message = {
                    'type': 'discovery',
                    'host_ip': self.host_ip,
                    'chat_port': self.chat_port,
                    'host_id': MY_ID,
                    'host_name': MY_NAME
                }
                self.broadcast_socket.sendto(json.dumps(discovery_message).encode('utf-8'), (broadcast_ip, self.discovery_port))
                time.sleep(2)
            except Exception as e:
                if self.running:
                    print(f"Erro no broadcast UDP: {e}")
                break

    def _accept_connections(self):
        while self.running:
            try:
                self.server_socket.settimeout(1.0)
                client_socket, client_address = self.server_socket.accept()
                print(f"Novo amigo conectado: {client_address[0]}:{client_address[1]}")
                self.clients[client_address] = client_socket
                threading.Thread(target=self._handle_client, args=(client_socket, client_address)).start()
                client_socket.send(json.dumps({'type': 'request_name', 'data': MY_ID}).encode('utf-8'))
            except socket.timeout:
                continue
            except Exception as e:
                if self.running:
                    print(f"Erro ao aceitar conexão: {e}")
                break

    def _handle_client(self, client_socket, client_address):
        try:
            while self.running:
                data = client_socket.recv(BUFFER_SIZE).decode('utf-8')
                if not data:
                    print(f"Amigo {self.client_names.get(client_address, client_address)} desconectou.")
                    del self.clients[client_address]
                    if client_address in self.client_names:
                        del self.client_names[client_address]
                    break

                message_obj = json.loads(data)
                if message_obj['type'] == 'name_intro':
                    remote_name = message_obj['name']
                    remote_id = message_obj['id']
                    self.client_names[client_address] = remote_name
                    print(f"\nCHAT DE {remote_name} ({remote_id}): Conectado.")
                    if remote_id not in CONTACTS:
                        CONTACTS[remote_id] = remote_name
                        print(f"Adicionado novo contato: {remote_name} (Código: {remote_id})")
                elif message_obj['type'] == 'chat_message':
                    sender_id = message_obj.get('sender_id', 'Desconhecido')
                    sender_name = CONTACTS.get(sender_id, self.client_names.get(client_address, f"Amigo ({sender_id[:8]})"))
                    message_content = message_obj['content']
                    save_message(sender_id, MY_ID, message_content, is_me=False)
                    print(f"[{sender_name}]: {message_content}")
                    self.broadcast_message(message_obj, sender_socket=client_socket)
        except Exception as e:
            if self.running:
                print(f"Erro ao lidar com cliente {client_address}: {e}")
            if client_address in self.clients:
                del self.clients[client_address]
            if client_address in self.client_names:
                del self.client_names[client_address]

    def broadcast_message(self, message_obj, sender_socket=None):
        message_json = json.dumps(message_obj).encode('utf-8')
        for addr, client_socket in list(self.clients.items()):
            if client_socket != sender_socket:
                try:
                    client_socket.sendall(message_json)
                except Exception as e:
                    print(f"Erro ao enviar mensagem para {addr}: {e}")
                    if addr in self.clients:
                        del self.clients[addr]
                    if addr in self.client_names:
                        del self.client_names[addr]

    def _handle_user_input(self):
        while self.running:
            try:
                message = input("")
                if message.lower() == 'sair':
                    self.stop()
                    break
                if message:
                    message_obj = {
                        'type': 'chat_message',
                        'sender_id': MY_ID,
                        'content': message,
                        'timestamp': datetime.now().isoformat()
                    }
                    save_message(MY_ID, "ALL", message, is_me=True)
                    print(f"[Eu]: {message}")
                    self.broadcast_message(message_obj)
            except EOFError:
                print("Entrada de usuário encerrada.")
                self.stop()
                break
            except Exception as e:
                print(f"Erro na entrada do usuário: {e}")
                self.stop()
                break

    def stop(self):
        print("Encerrando servidor...")
        self.running = False

        if self.broadcast_socket:
            try:
                self.broadcast_socket.close()
            except Exception as e:
                print(f"Erro ao fechar socket de broadcast: {e}")

        for client_socket in self.clients.values():
            try:
                client_socket.shutdown(socket.SHUT_RDWR)
                client_socket.close()
            except Exception as e:
                print(f"Erro ao fechar socket de cliente: {e}")
        self.clients.clear()

        try:
            self.server_socket.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        finally:
            self.server_socket.close()
        print("Servidor encerrado.")

class ChatClient:
    def __init__(self, chat_port):
        self.chat_port = chat_port
        self.client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.running = True
        self.connected_to_ip = None

    def discover_and_connect(self):
        print("\n--- Buscando chats disponíveis na rede local (Wi-Fi)... ---")
        discovery_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        discovery_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        discovery_socket.settimeout(5.0)

        try:
            discovery_socket.bind(('', DISCOVERY_PORT))
        except OSError as e:
            print(f"Erro ao iniciar escuta de descoberta (porta {DISCOVERY_PORT}): {e}")
            print("Pode ser que outro aplicativo esteja usando essa porta, ou o firewall esteja bloqueando.")
            print("Por favor, reinicie o aplicativo e tente novamente.")
            return False

        found_servers = {}

        start_time = time.time()
        while time.time() - start_time < 5:
            try:
                data, addr = discovery_socket.recvfrom(BUFFER_SIZE)
                message_obj = json.loads(data.decode('utf-8'))
                if message_obj.get('type') == 'discovery':
                    host_ip = message_obj['host_ip']
                    host_id = message_obj['host_id']
                    host_name = message_obj.get('host_name', 'Desconhecido')

                    if host_id == MY_ID:
                        continue

                    if host_id not in found_servers:
                        found_servers[host_id] = {'ip': host_ip, 'name': host_name}
                        print(f"Encontrado: [{len(found_servers)}] Chat de '{host_name}' (IP: {host_ip})")
            except socket.timeout:
                continue
            except json.JSONDecodeError:
                print("Mensagem de descoberta inválida recebida.")
                continue
            except Exception as e:
                print(f"Erro durante a descoberta: {e}")
                break

        discovery_socket.close()

        if not found_servers:
            print("Nenhum chat encontrado na sua rede local. Verifique se o amigo iniciou o chat como host.")
            print("Ou talvez eles não estejam na mesma rede Wi-Fi que você.")
            return False

        if len(found_servers) == 1:
            host_id = list(found_servers.keys())[0]
            host_info = found_servers[host_id]
            print(f"\nConectando-se automaticamente ao chat de '{host_info['name']}' ({host_info['ip']})...")
            return self._connect_to_server(host_info['ip'])
        else:
            print("\nChats encontrados:")
            options = list(found_servers.keys())
            for i, host_id in enumerate(options):
                info = found_servers[host_id]
                print(f"  {i+1}. '{info['name']}' (IP: {info['ip']})")

            while True:
                try:
                    choice_num = int(input("Digite o número do chat para conectar: ").strip())
                    if 1 <= choice_num <= len(options):
                        chosen_host_id = options[choice_num - 1]
                        chosen_host_info = found_servers[chosen_host_id]
                        print(f"Conectando a '{chosen_host_info['name']}' ({chosen_host_info['ip']})...")
                        return self._connect_to_server(chosen_host_info['ip'])
                    else:
                        print("Número inválido. Tente novamente.")
                except ValueError:
                    print("Entrada inválida. Digite um número.")
                except Exception as e:
                    print(f"Erro na escolha: {e}")
                    return False


    def _connect_to_server(self, target_host_ip):
        self.connected_to_ip = target_host_ip
        try:
            self.client_socket.connect((self.connected_to_ip, self.chat_port))
            print("Conectado ao servidor de chat!")

            intro_message = {
                'type': 'name_intro',
                'id': MY_ID,
                'name': MY_NAME
            }
            self.client_socket.send(json.dumps(intro_message).encode('utf-8'))

            threading.Thread(target=self._receive_messages).start()
            threading.Thread(target=self._handle_user_input).start()
            return True

        except ConnectionRefusedError:
            print(f"\nErro: Conexão recusada por {self.connected_to_ip}. Verifique se o servidor está rodando e a porta está livre.")
            self.running = False
            return False
        except socket.gaierror:
            print(f"\nErro: Endereço do host inválido {self.connected_to_ip}. Verifique o IP.")
            self.running = False
            return False
        except Exception as e:
            print(f"\nErro ao conectar: {e}")
            self.running = False
            return False

    def _receive_messages(self):
        try:
            while self.running:
                data = self.client_socket.recv(BUFFER_SIZE).decode('utf-8')
                if not data:
                    print("Servidor desconectou.")
                    self.stop()
                    break

                message_obj = json.loads(data)
                if message_obj['type'] == 'request_name':
                    server_id = message_obj.get('data')
                    if server_id and server_id not in CONTACTS:
                        CONTACTS[server_id] = f"Host ({server_id[:8]})"
                        print(f"Adicionado novo contato (host): Host ({server_id[:8]})")

                elif message_obj['type'] == 'chat_message':
                    sender_id = message_obj.get('sender_id', 'Desconhecido')
                    message_content = message_obj['content']
                    sender_name = CONTACTS.get(sender_id, f"Amigo ({sender_id[:8] if sender_id != 'Desconhecido' else '?'})")
                    save_message(sender_id, MY_ID, message_content, is_me=False)
                    print(f"[{sender_name}]: {message_content}")
        except Exception as e:
            if self.running:
                print(f"Erro ao receber mensagem: {e}")
            self.stop()

    def _handle_user_input(self):
        while self.running:
            try:
                message = input("")
                if message.lower() == 'sair':
                    self.stop()
                    break
                if message:
                    message_obj = {
                        'type': 'chat_message',
                        'sender_id': MY_ID,
                        'content': message,
                        'timestamp': datetime.now().isoformat()
                    }
                    save_message(MY_ID, self.connected_to_ip, message, is_me=True)
                    print(f"[Eu]: {message}")
                    self.client_socket.send(json.dumps(message_obj).encode('utf-8'))
            except EOFError:
                print("Entrada de usuário encerrada.")
                self.stop()
                break
            except Exception as e:
                print(f"Erro na entrada do usuário: {e}")
                self.stop()
                break

    def stop(self):
        print("Desconectando...")
        self.running = False
        try:
            self.client_socket.shutdown(socket.SHUT_RDWR)
            self.client_socket.close()
        except Exception as e:
            print(f"Erro ao fechar socket do cliente: {e}")
        print("Desconectado.")

MESSAGE_HISTORY = []

def save_message(sender_id, receiver_id, content, is_me):
    MESSAGE_HISTORY.append({
        'sender_id': sender_id,
        'receiver_id': receiver_id,
        'content': content,
        'is_me': is_me,
        'timestamp': datetime.now().isoformat()
    })

def display_message_history():
    if not MESSAGE_HISTORY:
        print("\n--- Nenhuma mensagem no histórico para esta sessão. ---")
        return

    print("\n--- Histórico de Mensagens ---")
    for msg in MESSAGE_HISTORY:
        sender_name = "Eu" if msg['is_me'] else CONTACTS.get(msg['sender_id'], f"Amigo ({msg['sender_id'][:8]})")
        print(f"[{sender_name}]: {msg['content']}")
    print("----------------------------")


def setup_user():

    global MY_ID, MY_NAME

    user_data = load_user_data()


    if user_data:

        MY_ID = user_data['id']

        MY_NAME = user_data['name']

        print(f"Bem-vindo de volta, {MY_NAME}! Seu código de chat é: {MY_ID}")

    else:
        print("Bem-vindo")

        MY_NAME = input("Por favor, digite seu nome de usuário: ").strip()

        while not MY_NAME:

            MY_NAME = input("O nome não pode ser vazio. Digite seu nome de usuário: ").strip()

        MY_ID = str(uuid.uuid4())

        save_user_data(MY_ID, MY_NAME)

        print(f"Olá, {MY_NAME}! Seu código de chat único foi gerado: {MY_ID}")

        print("Guarde este código para compartilhar com seus amigos.")

def main_menu():
    print("\n--- Menu Principal ---")
    print("1. Iniciar um novo chat (você será o host)")
    print("2. Conectar a um chat existente (busca automática)")
    print("3. Ver meu código de chat")
    print("4. Sair")
    return input("Escolha uma opção: ").strip()

def run_app():
    
    setup_user()

    current_chat_instance = None

    while True:
        choice = main_menu()

        if choice == '1':
            if current_chat_instance:
                print("Você já está em um chat. Saia primeiro para iniciar um novo.")
                continue

            my_ip = get_local_ip()
            if my_ip == "127.0.0.1":
                print("Não foi possível detectar seu IP local. Verifique sua conexão Wi-Fi.")
                continue

            current_chat_instance = ChatServer(my_ip, CHAT_PORT, DISCOVERY_PORT)
            current_chat_instance.start()
            while current_chat_instance.running:
                time.sleep(0.1)
            current_chat_instance = None

        elif choice == '2':
            if current_chat_instance:
                print("Você já está em um chat. Saia primeiro para conectar a outro.")
                continue

            client = ChatClient(CHAT_PORT)
            connected = client.discover_and_connect()
            if connected:
                current_chat_instance = client
                while current_chat_instance.running:
                    time.sleep(0.1)
                current_chat_instance = None
            else:
                print("Não foi possível conectar a um chat. Tente novamente.")
                time.sleep(2)

        elif choice == '3':
            print(f"\nSeu nome de chat: {MY_NAME}")
            print(f"Seu código de chat: {MY_ID}")
            print("\nCompartilhe este código com amigos para que eles possam te encontrar (se você for o host).")
            input("Pressione Enter para continuar...")

        elif choice == '4':
            if current_chat_instance:
                current_chat_instance.stop()
            print("Saindo do aplicativo. Adeus!")
            break
        else:
            print("Opção inválida. Por favor, tente novamente.")

if __name__ == "__main__":
    run_app()
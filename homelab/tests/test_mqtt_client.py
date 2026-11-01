"""MQTT wire-level tests using real loopback sockets and a minimal protocol fixture.
Not Mosquitto/Docker integration or evidence that a device/SQL worker received a message.
"""
import importlib.util
from pathlib import Path
import socket
import struct
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('native_mqtt',ROOT/'dashboard/mqtt_client.py')
mqtt=importlib.util.module_from_spec(spec)
spec.loader.exec_module(mqtt)


class BrokerFixture:
    def __init__(self, mode='publish'):
        self.mode=mode
        self.listener=socket.socket()
        self.listener.bind(('127.0.0.1',0));self.listener.listen()
        self.port=self.listener.getsockname()[1]
        self.listener.settimeout(.2)
        self.stop=threading.Event();self.delivered=threading.Event()
        self.subscriber=None;self.published=[];self.errors=[];self.connections=[];self.workers=[]
        self.thread=threading.Thread(target=self.accept,daemon=True);self.thread.start()

    def accept(self):
        while not self.stop.is_set():
            try:c,_=self.listener.accept()
            except socket.timeout:continue
            except OSError:return
            self.connections.append(c)
            t=threading.Thread(target=self.handle,args=(c,),daemon=True);self.workers.append(t);t.start()

    def handle(self,c):
        try:
            c.settimeout(4)
            header,body=mqtt.receive(c)
            if header!=0x10 or b'mqttuser' not in body or b'test-secret' not in body:raise ValueError('bad CONNECT')
            c.sendall(mqtt.packet(0x20,b'\0\x05' if self.mode=='reject' else b'\0\0'))
            if self.mode=='reject':return
            header,body=mqtt.receive(c)
            if header==0x32:
                size=struct.unpack('!H',body[:2])[0];name=body[2:2+size].decode();identifier=body[2+size:4+size];payload=body[4+size:]
                self.published.append((name,payload))
                c.sendall(mqtt.packet(0x40,b'\0\2' if self.mode=='badack' else identifier))
                if self.mode=='roundtrip':
                    self.subscriber.sendall(mqtt.packet(0x30,mqtt.utf8(name)+payload));self.delivered.set()
            elif header==0x82:
                size=struct.unpack('!H',body[2:4])[0];name=body[4:4+size].decode()
                self.subscriber=c
                c.sendall(mqtt.packet(0x90,body[:2]+b'\0'))
                if self.mode=='sample':
                    for i in range(20):
                        value=b'\xff' if i==0 else ('message-'+str(i)).encode()
                        c.sendall(mqtt.packet(0x31 if i==0 else 0x30,mqtt.utf8('home/data')+value))
                else:self.delivered.wait(4)
            else:raise ValueError('unexpected packet')
        except Exception as e:self.errors.append(type(e).__name__)
        finally:c.close()

    def close(self):
        self.stop.set();self.delivered.set();self.listener.close();self.thread.join(1)
        for c in self.connections:
            try:c.shutdown(socket.SHUT_RDWR)
            except OSError:pass
            c.close()
        for t in self.workers:t.join(1)


class MqttClientTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);(self.root/'.env').write_text('MQTT_PASSWORD=test-secret\n')

    def fixture(self,mode):
        broker=BrokerFixture(mode);self.addCleanup(broker.close)
        connect=socket.create_connection
        def local(address,timeout):
            self.assertEqual(address,('127.0.0.1',1884))
            return connect(('127.0.0.1',broker.port),timeout=timeout)
        patcher=patch.object(mqtt.socket,'create_connection',side_effect=local);patcher.start();self.addCleanup(patcher.stop)
        return broker

    def test_publish_real_qos1_frames_and_puback(self):
        broker=self.fixture('publish')
        result=mqtt.publish(self.root,'home/data','{"temp":31}')
        self.assertEqual(result['qos'],1)
        self.assertFalse(result['retained'])
        self.assertEqual(broker.published,[('home/data',b'{"temp":31}')])
        self.assertNotIn('test-secret',str(result))

    def test_sample_real_suback_and_binary_payload(self):
        self.fixture('sample')
        result=mqtt.sample(self.root,'home/#')
        self.assertEqual(len(result['messages']),20)
        self.assertIsNone(result['messages'][0]['payload'])
        self.assertTrue(result['messages'][0]['retained'])
        self.assertEqual(result['messages'][1]['payload'],'message-1')

    def test_roundtrip_subscribes_before_publish(self):
        self.fixture('roundtrip')
        result=mqtt.selftest(self.root)
        self.assertIn('thành công',result['message'])
        self.assertTrue(result['topic'].startswith('maychu247/check/'))

    def test_bad_auth_or_bad_ack_never_reports_success(self):
        broker=self.fixture('reject')
        with self.assertRaisesRegex(RuntimeError,'xác thực'):mqtt.publish(self.root,'home/data','x')
        self.assertEqual(broker.published,[])

    def test_wrong_puback_never_reports_success(self):
        self.fixture('badack')
        with self.assertRaisesRegex(RuntimeError,'PUBACK'):
            mqtt.publish(self.root,'home/data','hello')

    def test_invalid_topics_and_payload_rejected_before_network(self):
        with patch.object(mqtt.socket,'create_connection') as connect:
            for name in ('', 'home/#','home/+','$SYS/x','home/\0data'):
                with self.assertRaises(ValueError):mqtt.publish(self.root,name,'x')
            with self.assertRaises(ValueError):mqtt.publish(self.root,'home/data','x'*16385)
            with self.assertRaises(ValueError):mqtt.sample(self.root,'home/#/invalid')
            connect.assert_not_called()


if __name__=='__main__':unittest.main()

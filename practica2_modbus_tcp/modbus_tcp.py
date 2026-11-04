import socket
import sys
import logging
import struct

AUTOR = "Sergio Andres Avila Pelaez"

class ExceptionModbus(Exception):
    """The server answered, but with a Modbus exception response."""
    CODES={
        1:"Illegal function",
        2:"Illegal data address",
        3:"Illegal data value",
        4:"Server device failure",
        5:"Acknowledge",
        6:"Server device busy",
        8:"Memory parity error",
        10:"Gateway path unavailable",
        11:"Gateway target device failed to respond",
    }

    def __init__(self,function,code):
        self.function=function    # the original function code (without the 0x80 bit)
        self.code=code            # the Modbus exception code
        self.description=self.CODES.get(code,"Unknown exception")
        super().__init__(f"Function 0x{function:02X} failed with exception {code}: {self.description}")

class ErrorConexion(Exception):
    """No (valid) answer from the server: refused, timeout, unreachable, dropped."""

class ModbusTCP:
    def __init__(self,host,port=502,timeout=3):
        self.host=host
        self.port=port
        self.timeout=timeout
        self.client=None
        self.tid=0   # transaction id counter, one per connection

    def next_tid(self):
        # Transaction id is 2 bytes, so wrap around after 0xFFFF
        self.tid=(self.tid+1)%0x10000
        return self.tid

    def connect(self):
        # No "with" here: a with block closes the socket as soon as it exits,
        # so we'd be returning an already-closed socket.
        try:
            self.client=socket.create_connection((self.host,self.port),timeout=self.timeout)
        except OSError as e:    # refused, timeout, unreachable, bad hostname...
            raise ErrorConexion(f"Cannot connect to {self.host}:{self.port}: {e}") from e
        logging.info("Connection created to host %s",self.host)

    def close(self):
        if self.client is None:
            return
        try:
            self.client.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.client.close()
        self.client=None
        logging.info("Connection closed")

    def execute(self,data):
        try:
            self.client.sendall(data.pack())
        except OSError as e:
            raise ErrorConexion(f"Send failed: {e}") from e

    def recv_exact(self,n):
        # TCP is a stream: one recv() may return fewer bytes than asked, so loop
        buf=b""
        while len(buf)<n:
            try:
                chunk=self.client.recv(n-len(buf))
            except OSError as e:    # includes the read timeout
                raise ErrorConexion(f"Receive failed: {e}") from e
            if not chunk:   # empty bytes = server closed the connection
                raise ErrorConexion("Connection closed by server")
            buf+=chunk
        return buf

    def receive(self):
        # Read the 7-byte MBAP header, get the length, then read the rest (the PDU)
        mbap=self.recv_exact(7)
        tid,_pid,length,_uid=struct.unpack(">HHHB",mbap)
        pdu=self.recv_exact(length-1)   # length counts unit_id, already read
        return tid,pdu

class MBAPHeader:
    def __init__(self,func,init_addr,qty,transaction_id=0,unit_id=0xFF):
        # PDU fields
        self.func=func
        self.init_addr=init_addr
        self.qty=qty
        # MBAP fields (protocol_id is always 0 for Modbus, length is calculated)
        self.transaction_id=transaction_id
        self.protocol_id=0
        self.unit_id=unit_id

    def pack_pdu(self):
        # ">BHH" = big-endian: func (1 byte), init_addr (2 bytes), qty (2 bytes)
        return struct.pack(">BHH",self.func,self.init_addr,self.qty)

    def pack(self):
        pdu=self.pack_pdu()
        length=1+len(pdu)   # unit_id (1 byte) + PDU
        mbap=struct.pack(">HHHB",self.transaction_id,self.protocol_id,length,self.unit_id)
        return mbap+pdu

class ReadHoldingRegister(MBAPHeader):
    FUNC=0x03

    def __init__(self,init_addr=0,qty=1,transaction_id=0,unit_id=0xFF):
        # func is fixed for this class, so the user never passes it
        super().__init__(self.FUNC,init_addr,qty,transaction_id,unit_id)

    def parse_response(self,pdu):
        _,byte_count=struct.unpack(">BB",pdu[:2])  # response has a byte count instead of an address
        data=pdu[2:2+byte_count]
        # each register is 2 bytes, big-endian
        return struct.unpack(f">{byte_count//2}H",data)

def _check_exception(pdu):
    # An exception response is func|0x80 followed by the exception code
    if pdu[0] & 0x80:
        raise ExceptionModbus(pdu[0] & 0x7F,pdu[1])

def _transact(client,request_cls,init_addr,count_or_value,transaction_id):
    if transaction_id is None:             # None = let the client generate it
        transaction_id=client.next_tid()
    request=request_cls(init_addr,count_or_value,transaction_id)
    client.execute(request)
    tid,pdu=client.receive()
    if tid!=transaction_id:                # response must belong to this request
        raise RuntimeError(f"Transaction id mismatch: sent {transaction_id}, got {tid}")
    _check_exception(pdu)                  # parse_response only sees successful replies
    return request.parse_response(pdu)

def read_holding_register(client,init_addr=0,qty=1,transaction_id=None):
    return _transact(client,ReadHoldingRegister,init_addr,qty,transaction_id)

class ReadInputRegisters(ReadHoldingRegister):
    # Same request/response layout as holding registers, only the function code changes
    FUNC=0x04

def read_input_registers(client,init_addr=0,qty=1,transaction_id=None):
    return _transact(client,ReadInputRegisters,init_addr,qty,transaction_id)

class ReadCoils(MBAPHeader):
    FUNC=0x01

    # The request is identical to the register reads: func + start address + quantity
    def __init__(self,init_addr=0,qty=1,transaction_id=0,unit_id=0xFF):
        super().__init__(self.FUNC,init_addr,qty,transaction_id,unit_id)

    def parse_response(self,pdu):
        _,byte_count=struct.unpack(">BB",pdu[:2])
        if byte_count!=(self.qty+7)//8:    # ceil(qty/8) without importing math
            raise RuntimeError(f"Expected {(self.qty+7)//8} bytes, got {byte_count}")
        data=pdu[2:2+byte_count]
        # Coil i lives in byte i//8, bit i%8 (first coil = least significant bit)
        # Only qty bits are read, so the zero padding in the last byte is ignored
        return [bool((data[i//8]>>(i%8))&1) for i in range(self.qty)]

def read_coils(client,init_addr=0,qty=1,transaction_id=None):
    return _transact(client,ReadCoils,init_addr,qty,transaction_id)

class ReadDiscreteInputs(ReadCoils):
    # Same request/response layout as coils, only the function code changes
    FUNC=0x02

def read_discrete_inputs(client,init_addr=0,qty=1,transaction_id=None):
    return _transact(client,ReadDiscreteInputs,init_addr,qty,transaction_id)

class WriteRegistry(MBAPHeader):
    FUNC=0x06

    def __init__(self,init_addr=0,value=0,transaction_id=0,unit_id=0xFF):
        if not -32768<=value<=32767:       # range of a signed 16-bit integer
            raise ValueError(f"value {value} does not fit in a signed 16-bit register")
        # qty=1: this function always writes exactly one register
        super().__init__(self.FUNC,init_addr,1,transaction_id,unit_id)
        self.value=value

    def pack_pdu(self):
        # ">BHh": func (1 byte), address (2 bytes unsigned), value (2 bytes SIGNED)
        return struct.pack(">BHh",self.FUNC,self.init_addr,self.value)

    def parse_response(self,pdu):
        func,addr,value=struct.unpack(">BHh",pdu[:5])
        # A successful write response is an exact echo of the request
        if (func,addr,value)!=(self.FUNC,self.init_addr,self.value):
            raise RuntimeError(f"Echo mismatch: sent {(self.FUNC,self.init_addr,self.value)}, got {(func,addr,value)}")
        return value

def write_registry(client,init_addr=0,value=0,transaction_id=None):
    return _transact(client,WriteRegistry,init_addr,value,transaction_id)

class WriteCoil(MBAPHeader):
    FUNC=0x05
    ON=0xFF00     # the only value Modbus accepts for "on"
    OFF=0x0000

    def __init__(self,init_addr=0,value=False,transaction_id=0,unit_id=0xFF):
        # qty=1: this function always writes exactly one coil
        super().__init__(self.FUNC,init_addr,1,transaction_id,unit_id)
        self.value=bool(value)

    def pack_pdu(self):
        raw=self.ON if self.value else self.OFF
        # ">BHH": func (1 byte), address (2 bytes), raw coil value (2 bytes)
        return struct.pack(">BHH",self.FUNC,self.init_addr,raw)

    def parse_response(self,pdu):
        func,addr,raw=struct.unpack(">BHH",pdu[:5])
        expected=self.ON if self.value else self.OFF
        # A successful write response is an exact echo of the request
        if (func,addr,raw)!=(self.FUNC,self.init_addr,expected):
            raise RuntimeError(f"Echo mismatch: sent {(self.FUNC,self.init_addr,expected)}, got {(func,addr,raw)}")
        return raw==self.ON

def write_coil(client,init_addr=0,value=False,transaction_id=None):
    return _transact(client,WriteCoil,init_addr,value,transaction_id)

def main():
    print("Hello world")

if __name__ == "__main__":
    sys.exit(main())
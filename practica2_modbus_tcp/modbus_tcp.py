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
    """No (valid) answer from the server: refused, unreachable, dropped."""

class ErrorTimeout(ErrorConexion):
    """The server did not answer within the timeout."""

class ErrorProtocolo(Exception):
    """The server answered, but the reply is not what the protocol requires."""

def _conn_error(message,e):
    # A timeout is a more specific kind of connection error
    cls=ErrorTimeout if isinstance(e,TimeoutError) else ErrorConexion
    return cls(f"{message}: {e}")

class ModbusTCP:
    def __init__(self,host,port=502,timeout=3,unit_id=0xFF):
        self.host=host
        self.port=port
        self.timeout=timeout
        self.unit_id=unit_id   # sent in every request made through this client
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
            raise _conn_error(f"Cannot connect to {self.host}:{self.port}",e) from e
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
        frame=data.pack()
        logging.debug("TX %s",frame.hex(" "))   # only visible when logging is set to DEBUG
        try:
            self.client.sendall(frame)
        except OSError as e:
            raise _conn_error("Send failed",e) from e

    def recv_exact(self,n):
        # TCP is a stream: one recv() may return fewer bytes than asked, so loop
        buf=b""
        while len(buf)<n:
            try:
                chunk=self.client.recv(n-len(buf))
            except OSError as e:    # includes the read timeout
                raise _conn_error("Receive failed",e) from e
            if not chunk:   # empty bytes = server closed the connection
                raise ErrorConexion("Connection closed by server")
            buf+=chunk
        return buf

    def receive(self):
        # Read the 7-byte MBAP header, get the length, then read the rest (the PDU)
        mbap=self.recv_exact(7)
        tid,_pid,length,_uid=struct.unpack(">HHHB",mbap)
        pdu=self.recv_exact(length-1)   # length counts unit_id, already read
        logging.debug("RX %s",(mbap+pdu).hex(" "))
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

def _transact(client,request_cls,transaction_id,*fields):
    if transaction_id is None:             # None = let the client generate it
        transaction_id=client.next_tid()
    request=request_cls(*fields,transaction_id=transaction_id,unit_id=client.unit_id)
    client.execute(request)
    tid,pdu=client.receive()
    if tid!=transaction_id:                # response must belong to this request
        raise ErrorProtocolo(f"Transaction id mismatch: sent {transaction_id}, got {tid}")
    try:
        _check_exception(pdu)              # parse_response only sees successful replies
        return request.parse_response(pdu)
    except (struct.error,IndexError) as e: # reply too short / malformed
        raise ErrorProtocolo(f"Malformed response: {e}") from e

def read_holding_register(client,init_addr=0,qty=1,transaction_id=None):
    return _transact(client,ReadHoldingRegister,transaction_id,init_addr,qty)

class ReadInputRegisters(ReadHoldingRegister):
    # Same request/response layout as holding registers, only the function code changes
    FUNC=0x04

def read_input_registers(client,init_addr=0,qty=1,transaction_id=None):
    return _transact(client,ReadInputRegisters,transaction_id,init_addr,qty)

class ReadCoils(MBAPHeader):
    FUNC=0x01

    # The request is identical to the register reads: func + start address + quantity
    def __init__(self,init_addr=0,qty=1,transaction_id=0,unit_id=0xFF):
        super().__init__(self.FUNC,init_addr,qty,transaction_id,unit_id)

    def parse_response(self,pdu):
        _,byte_count=struct.unpack(">BB",pdu[:2])
        if byte_count!=(self.qty+7)//8:    # ceil(qty/8) without importing math
            raise ErrorProtocolo(f"Expected {(self.qty+7)//8} bytes, got {byte_count}")
        data=pdu[2:2+byte_count]
        # Coil i lives in byte i//8, bit i%8 (first coil = least significant bit)
        # Only qty bits are read, so the zero padding in the last byte is ignored
        return [bool((data[i//8]>>(i%8))&1) for i in range(self.qty)]

def read_coils(client,init_addr=0,qty=1,transaction_id=None):
    return _transact(client,ReadCoils,transaction_id,init_addr,qty)

class ReadDiscreteInputs(ReadCoils):
    # Same request/response layout as coils, only the function code changes
    FUNC=0x02

def read_discrete_inputs(client,init_addr=0,qty=1,transaction_id=None):
    return _transact(client,ReadDiscreteInputs,transaction_id,init_addr,qty)

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
            raise ErrorProtocolo(f"Echo mismatch: sent {(self.FUNC,self.init_addr,self.value)}, got {(func,addr,value)}")
        return value

def write_registry(client,init_addr=0,value=0,transaction_id=None):
    return _transact(client,WriteRegistry,transaction_id,init_addr,value)

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
            raise ErrorProtocolo(f"Echo mismatch: sent {(self.FUNC,self.init_addr,expected)}, got {(func,addr,raw)}")
        return raw==self.ON

def write_coil(client,init_addr=0,value=False,transaction_id=None):
    return _transact(client,WriteCoil,transaction_id,init_addr,value)

class WriteMultipleRegistries(MBAPHeader):
    FUNC=0x10
    MAX_QTY=123    # Modbus limit for this function, so the PDU fits in 253 bytes

    def __init__(self,init_addr=0,values=(1,),transaction_id=0,unit_id=0xFF):
        values=list(values)
        if not 1<=len(values)<=self.MAX_QTY:
            raise ValueError(f"Need between 1 and {self.MAX_QTY} values, got {len(values)}")
        for v in values:
            if not -32768<=v<=32767:       # same signed 16-bit range as WriteRegistry
                raise ValueError(f"value {v} does not fit in a signed 16-bit register")
        # qty is derived from the values, so the two can never disagree
        super().__init__(self.FUNC,init_addr,len(values),transaction_id,unit_id)
        self.values=values
        self.byte_count=len(values)*2      # each register is 2 bytes

    def pack_pdu(self):
        # ">BHHB" + one signed short per value:
        # func (1), address (2), qty (2), byte_count (1), then the values (2 each)
        return struct.pack(f">BHHB{self.qty}h",self.FUNC,self.init_addr,self.qty,
                           self.byte_count,*self.values)

    def parse_response(self,pdu):
        # The reply echoes only function, address and quantity (not the values)
        func,addr,qty=struct.unpack(">BHH",pdu[:5])
        if (func,addr,qty)!=(self.FUNC,self.init_addr,self.qty):
            raise ErrorProtocolo(f"Echo mismatch: sent {(self.FUNC,self.init_addr,self.qty)}, got {(func,addr,qty)}")
        return qty

def write_multiple_registries(client,init_addr=0,values=(1,),transaction_id=None):
    return _transact(client,WriteMultipleRegistries,transaction_id,init_addr,values)

class WriteMultipleCoils(MBAPHeader):
    FUNC=0x0F
    MAX_QTY=1968   # Modbus limit for this function: 246 data bytes * 8 bits (0x7B0)

    def __init__(self,init_addr=0,values=(True,),transaction_id=0,unit_id=0xFF):
        values=[bool(v) for v in values]
        if not 1<=len(values)<=self.MAX_QTY:
            raise ValueError(f"Need between 1 and {self.MAX_QTY} values, got {len(values)}")
        # qty is derived from the values, so the two can never disagree
        super().__init__(self.FUNC,init_addr,len(values),transaction_id,unit_id)
        self.values=values
        self.byte_count=(len(values)+7)//8     # ceil(qty/8): 8 coils per byte

    def pack_bits(self):
        # Inverse of ReadCoils: coil i goes to byte i//8, bit i%8 (first coil = LSB)
        data=bytearray(self.byte_count)         # starts as all zeros, so padding is 0
        for i,on in enumerate(self.values):
            if on:
                data[i//8]|=1<<(i%8)            # set bit i%8 of that byte
        return bytes(data)

    def pack_pdu(self):
        # ">BHHB" + "{n}s": func (1), address (2), qty (2), byte_count (1),
        # then n raw bytes (the packed coil bits)
        return struct.pack(f">BHHB{self.byte_count}s",self.FUNC,self.init_addr,self.qty,
                           self.byte_count,self.pack_bits())

    def parse_response(self,pdu):
        # The reply echoes only function, address and quantity (not the values)
        func,addr,qty=struct.unpack(">BHH",pdu[:5])
        if (func,addr,qty)!=(self.FUNC,self.init_addr,self.qty):
            raise ErrorProtocolo(f"Echo mismatch: sent {(self.FUNC,self.init_addr,self.qty)}, got {(func,addr,qty)}")
        return qty

def write_multiple_coils(client,init_addr=0,values=(True,),transaction_id=None):
    return _transact(client,WriteMultipleCoils,transaction_id,init_addr,values)

class ReadWriteMultipleRegistries(ReadHoldingRegister):
    # The response is identical to a holding register read (func + byte_count + values),
    # so parse_response is inherited. init_addr/qty hold the READ part of the request.
    FUNC=0x17
    MAX_READ_QTY=125
    MAX_WRITE_QTY=121

    def __init__(self,read_addr=0,read_qty=1,write_addr=0,write_values=(1,),
                 transaction_id=0,unit_id=0xFF):
        write_values=list(write_values)
        if not 1<=read_qty<=self.MAX_READ_QTY:
            raise ValueError(f"read_qty must be between 1 and {self.MAX_READ_QTY}, got {read_qty}")
        if not 1<=len(write_values)<=self.MAX_WRITE_QTY:
            raise ValueError(f"Need between 1 and {self.MAX_WRITE_QTY} values to write, got {len(write_values)}")
        for v in write_values:
            if not -32768<=v<=32767:
                raise ValueError(f"value {v} does not fit in a signed 16-bit register")
        # Goes through ReadHoldingRegister.__init__, which uses our FUNC (0x17)
        super().__init__(read_addr,read_qty,transaction_id,unit_id)
        self.write_addr=write_addr
        self.write_values=write_values
        self.write_qty=len(write_values)           # derived, like the other multi-writes
        self.write_byte_count=self.write_qty*2

    def pack_pdu(self):
        # func (1), read addr (2), read qty (2), write addr (2), write qty (2),
        # write byte_count (1), then the write values (2 each, signed)
        return struct.pack(f">BHHHHB{self.write_qty}h",self.FUNC,self.init_addr,self.qty,
                           self.write_addr,self.write_qty,self.write_byte_count,
                           *self.write_values)

def read_write_multiple_registries(client,read_addr=0,read_qty=1,write_addr=0,
                                   write_values=(1,),transaction_id=None):
    return _transact(client,ReadWriteMultipleRegistries,transaction_id,
                     read_addr,read_qty,write_addr,write_values)

def main():
    print("Hello world")

if __name__ == "__main__":
    sys.exit(main())
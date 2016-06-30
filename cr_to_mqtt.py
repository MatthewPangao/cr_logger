import paho.mqtt.client as mqtt
import time
import logging
import json
import datetime
import dateutil.parser
import os.path
import threading
from PyCampbellCR1000.pycampbellcr1000.exceptions import NoDeviceException

logging.basicConfig(level=logging.INFO, 
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logging.getLogger('pycampbellcr1000').setLevel(logging.WARN)
logging.getLogger('pylink').setLevel(logging.WARN)


LOG = logging.getLogger(__name__)
TABLE_FILE = "tables.json"
MQHOST = "localhost"
MQPORT = 9999
mqconnect = threading.Event()

from PyCampbellCR1000.pycampbellcr1000 import CR1000

def load_tables():
    'load tables parsing datetimes'
    if os.path.exists(TABLE_FILE):
        with open(TABLE_FILE, 'r') as fp:
            tables = json.load(fp)            
        
        return {k:dateutil.parser.parse(v) for k,v in tables.items()}
    
    return None
def save_tables(tables):
    'save tables fixing datatimes to strings'
    # serialize first so if that breaks, we don't overwrite the file
    data = json.dumps({k:v.isoformat() for k,v in tables.items()})
    with open(TABLE_FILE, 'w') as fp:
        fp.write(data)
def emit_record(client, topic, rec):
    
    LOG.info("emit to {}: {}".format(topic, rec))
    # make it serializable
    d = rec['Datetime']
    rec['Datetime'] = rec['Datetime'].isoformat()
    client.publish(topic,json.dumps(rec), qos=2)
    rec['Datetime'] = d
    #for x,v in rec.items():
        #print (x,v)

# The callback for when the client receives a CONNACK response from the server.
def on_connect(client, userdata, flags, rc):
    LOG.info("MQTT Connected with result code "+str(rc))
    mqconnect.set()

# The callback for when a PUBLISH message is received from the server.
def on_message(client, userdata, msg):
    LOG.info("rcv: "+msg.topic+" "+str(msg.payload))

    
def connect_and_download():    
    LOG.debug("creating device.")
    
    client = mqtt.Client()

    if (client.connect(MQHOST, MQPORT, 60) != mqtt.MQTT_ERR_SUCCESS):
        print("Failed to connect to MQTT server.")
        exit(-1)
        
    client.on_connect = on_connect
    client.on_message = on_message
    
    client.loop_start()

    tables = load_tables()
    
    try:
        
        device = CR1000.from_url('serial:/dev/ttyACM0:57600',
                             src_addr=4004,
                             #src_addr=4003,                         
                             dest_addr=1235,
                             #dest_addr=1234,
                             timeout=1)
        
        LOG.debug ('have device: {}'.format(device))                      
        LOG.info ("device time: {}".format(device.gettime()))
                        
        if tables == None:        
            tlist = device.list_tables()
            tables ={x: datetime.datetime.now() for x in tlist if not x in ['Status', 'Public']}        
            save_tables(tables)
        mqroot = 'CR6/{}'.format(device.serialNo)
        
        if not mqconnect.wait(timeout=30):
            LOG.fatal("Failed to connect to MQ server")
            return
        
        for tablename, lastcollect in tables.items():              
            #if tablename != 'WO209060_PBM':
                #continue
            
            LOG.info("Download {} from {}".format(tablename, lastcollect))
            
            for items in device.get_data_generator(tablename, 
                                                   start_date = lastcollect):            
                for record in items:
                    LOG.debug("got record: {}".format(record))
                    emit_record(client, mqroot+'/'+tablename, record)
                    time.sleep(0.1)
                tables[tablename] = items[-1]['Datetime'] + datetime.timedelta(seconds=1)
                
        time.sleep(5)
        
    finally:
        
        save_tables(tables)
        client.disconnect()
        time.sleep(1)
        client.loop_stop()        
        client.on_connect = None
        client.on_message = None 

if __name__ == "__main__":
    
    while True:
        try:
            if connect_and_download():
                time.sleep(27)
            
        except NoDeviceException:
            LOG.fatal("No response from datalogger.")        
        time.sleep(3)
    
        

        
import serial_protocol
import serial
import threading
import queue
from flask import Flask, render_template
from flask_socketio import SocketIO, emit
import time

app = Flask(__name__)
app.config['SECRET_KEY'] = 'radar-web-interface-secret'
socketio = SocketIO(app, cors_allowed_origins="*")

# Create a thread-safe queue to communicate between threads
data_queue = queue.Queue()

# Global variable to track serial connection status
serial_connected = False
ser = None

def serial_reader():
    """Thread function to continuously read data from the serial port"""
    global serial_connected, ser
    try:
        ser = serial.Serial('/dev/ttyAMA0', 256000, timeout=1)
        serial_connected = True
        print("Serial connection established")
        
        while True:
            try:
                data = ser.read_until(serial_protocol.REPORT_TAIL)
                data_queue.put(data)
            except serial.SerialException as e:
                print(f"Serial read error: {e}")
                serial_connected = False
                break
    except Exception as e:
        print(f"Failed to open serial port: {e}")
        serial_connected = False

def process_data():
    """Thread function to process data from the queue and emit to clients"""
    while True:
        if not data_queue.empty():
            serial_protocol_line = data_queue.get()
            
            # Check if the frame header and tail are present
            if serial_protocol.REPORT_HEADER in serial_protocol_line and serial_protocol.REPORT_TAIL in serial_protocol_line:
                # Extract the target values
                all_target_values = serial_protocol.read_radar_data(serial_protocol_line)
                
                if all_target_values is not None:
                    target1_x, target1_y, target1_speed, target1_distance_res, \
                    target2_x, target2_y, target2_speed, target2_distance_res, \
                    target3_x, target3_y, target3_speed, target3_distance_res = all_target_values
                    
                    # Create data structure for all targets
                    targets = []
                    for i, (x, y, speed, dist_res) in enumerate([
                        (target1_x, target1_y, target1_speed, target1_distance_res),
                        (target2_x, target2_y, target2_speed, target2_distance_res),
                        (target3_x, target3_y, target3_speed, target3_distance_res)
                    ], 1):
                        # Only include targets that are actually detected (not at origin)
                        if x != 0 or y != 0:
                            targets.append({
                                'id': i,
                                'x': x,
                                'y': y,
                                'speed': speed,
                                'distance_res': dist_res
                            })
                    
                    # Emit data to all connected clients
                    socketio.emit('radar_data', {
                        'targets': targets,
                        'connected': serial_connected,
                        'timestamp': time.time()
                    })
        
        time.sleep(0.01)  # Small delay to prevent CPU overload

@app.route('/')
def index():
    """Serve the main HTML page"""
    return render_template('index.html')

@socketio.on('connect')
def handle_connect():
    """Handle client connection"""
    print('Client connected')
    emit('status', {'connected': serial_connected})

@socketio.on('disconnect')
def handle_disconnect():
    """Handle client disconnection"""
    print('Client disconnected')

@socketio.on('enable_multi_target_tracking')
def handle_enable_tracking(data):
    """Enable multi-target tracking"""
    global ser
    if ser and serial_connected:
        try:
            result = serial_protocol.multi_target_tracking(ser, data.get('enable', True))
            emit('tracking_status', {'success': result, 'enabled': data.get('enable', True)})
        except Exception as e:
            print(f"Error setting multi-target tracking: {e}")
            emit('tracking_status', {'success': False, 'error': str(e)})

if __name__ == '__main__':
    # Create and start the serial reader thread
    serial_thread = threading.Thread(target=serial_reader, daemon=True)
    serial_thread.start()
    
    # Create and start the data processing thread
    process_thread = threading.Thread(target=process_data, daemon=True)
    process_thread.start()
    
    # Start the Flask application
    print("Starting web interface on http://0.0.0.0:3030")
    socketio.run(app, host='0.0.0.0', port=3030, debug=False)

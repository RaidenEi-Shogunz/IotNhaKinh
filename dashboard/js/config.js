export const CONFIG = {
    username: sessionStorage.getItem('aio_username') || '',
    key:      '',
    mqttUrl: 'wss://io.adafruit.com/mqtt',
    feeds: {
        sensorData:    'sensor-data',    // v5.0: batch feed (moisture+temp+light+humidity+co2+pump)
        moisture:      'soil-moisture',  // legacy: van subscribe de backward compat
        temperature:   'temperature',
        light:         'light-intensity',
        humidity:      'humidity',
        co2:           'co2-level',
        pumpStatus:    'pump-status',
        pumpCmd:       'pump-cmd',
        mode:          'greenhouse-mode',
        threshold:     'moisture-threshold',
        aiStatus:      'ai-status',
        wateringEvent: 'watering-event',
        alertStatus:   'alert-status',
    },
    gaugeMax: {
        moisture:    100,
        temperature: 50,
        light:       10000,
        humidity:    100,
        co2:         1200,
        ec:          5,
        ph:          14,
    },
    maxDataPoints: 50,
};

export const state = {
    connected:   false,
    currentMode: 'AUTO',
    pumpOn:      false,
    activeChart: 'moisture',
    msgCount:    0,
    currentSimTime: '06:00',
    history: {
        timestamps:  [],
        moisture:    [],
        temperature: [],
        light:       [],
        humidity:    [],
        co2:         [],
        ec:          [],
        ph:          [],
        predictions: [],
    },
    alerts:      [],
    wateringLog: [],
    lastSimTime: null,
};

export const DOM = {
    gauges: {},
    values: {},
    statuses: {},
    simClock: null,
    weatherDisplay: null,
    connectionStatus: null,
    pumpStatus: null,
    aiDisplay: null,
    alertList: null,
    chartTabs: null,
};

const CACHE_NAME = 'smart-greenhouse-v1';
const ASSETS_TO_CACHE = [
  './',
  './index.html',
  './ai_camera.html',
  './css/style.css',
  './css/ai_pipeline.css',
  './js/config.js',
  './js/utils.js',
  './js/chartManager.js',
  './js/localApiService.js',
  './js/mqttService.js',
  './js/uiController.js',
  './js/main.js',
  './js/gemini_vision.js',
  './js/leaf_gate.js',
  './manifest.json',
  'https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap',
  'https://cdn.jsdelivr.net/npm/chart.js'
];

// Install event: cache assets
self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache => {
        console.log('[ServiceWorker] Caching app shell');
        return cache.addAll(ASSETS_TO_CACHE);
      })
      .then(() => self.skipWaiting())
  );
});

// Activate event: cleanup old caches
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keyList => {
      return Promise.all(keyList.map(key => {
        if (key !== CACHE_NAME) {
          console.log('[ServiceWorker] Removing old cache', key);
          return caches.delete(key);
        }
      }));
    })
  );
  self.clients.claim();
});

// Fetch event: network first, fallback to cache for API requests, cache first for static assets
self.addEventListener('fetch', event => {
  // Ignore API calls, let them pass through or fail
  if (event.request.url.includes('/api/')) {
    return;
  }
  
  event.respondWith(
    caches.match(event.request)
      .then(response => {
        return response || fetch(event.request).then(fetchRes => {
          // Cache new static assets
          if (event.request.method === 'GET' && !event.request.url.startsWith('chrome-extension')) {
            return caches.open(CACHE_NAME).then(cache => {
              cache.put(event.request, fetchRes.clone());
              return fetchRes;
            });
          }
          return fetchRes;
        });
      })
      .catch(() => {
        // Fallback for offline if not in cache (could return offline page)
      })
  );
});

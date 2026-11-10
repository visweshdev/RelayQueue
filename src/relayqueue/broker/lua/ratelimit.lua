-- KEYS bucket (SHA256 of API key); ARGV rate,capacity
local t = redis.call('TIME')
local now = tonumber(t[1]) + tonumber(t[2]) / 1000000
local state = redis.call('HMGET', KEYS[1], 'tokens', 'time')
local tokens = tonumber(state[1]) or tonumber(ARGV[2])
local previous = tonumber(state[2]) or now
tokens = math.min(tonumber(ARGV[2]), tokens + math.max(0, now - previous) * ARGV[1])
local allowed = 0
if tokens >= 1 then tokens = tokens - 1; allowed = 1 end
redis.call('HSET', KEYS[1], 'tokens', tokens, 'time', now)
redis.call('EXPIRE', KEYS[1], 60)
return allowed

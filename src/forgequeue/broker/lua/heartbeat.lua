-- KEYS owner,leases; ARGV id,token,lease_ms
if redis.call('GET', KEYS[1]) ~= ARGV[2] then return 0 end
local t = redis.call('TIME')
local now = tonumber(t[1]) * 1000 + tonumber(t[2]) / 1000
redis.call('PEXPIRE', KEYS[1], ARGV[3])
redis.call('ZADD', KEYS[2], now + tonumber(ARGV[3]), ARGV[1])
return 1

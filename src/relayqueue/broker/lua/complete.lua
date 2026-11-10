-- Compare-and-delete: old attempts cannot remove a successor's lease.
-- KEYS owner,leases; ARGV id,token
if redis.call('GET', KEYS[1]) ~= ARGV[2] then return 0 end
redis.call('DEL', KEYS[1])
redis.call('ZREM', KEYS[2], ARGV[1])
return 1

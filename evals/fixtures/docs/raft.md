# Raft consensus

## Leader election

Servers start as followers. A follower that hears nothing from a leader becomes a candidate and requests votes. A candidate that wins a majority of votes becomes the leader.

## Log replication

The leader appends client commands to its log and replicates them to followers. An entry is committed once a majority of servers have stored it.

// One shared Socket.io connection for the whole app. The backend broadcasts
// every event globally (see api/app.py) rather than scoping to a room per
// run -- fine for a single-operator dashboard -- so components just filter
// the stream by runId themselves (see useRunEvents in App.jsx).
import { io } from 'socket.io-client'
import { API_URL } from './api'

export const socket = io(API_URL, { autoConnect: true })

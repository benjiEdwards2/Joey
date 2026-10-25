package net.joeyhome.media.policy

enum class OfflineKind {
    /** Joey Media can't be reached: "Check that this TV is online". */
    NETWORK,

    /** Joey Media answers /healthz, but the page itself failed (bad URL, main-frame error or 5xx). */
    PAGE,
}

/** JY-191 (V2): which Offline wording to show, from a fresh /healthz probe after the failure. */
object OfflinePolicy {
    fun kind(serverReachable: Boolean): OfflineKind = if (serverReachable) OfflineKind.PAGE else OfflineKind.NETWORK
}

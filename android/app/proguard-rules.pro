# Nothing reflective of our own: JSON is read by hand with org.json.

# WorkManager keeps its queue in a Room database, which Room instantiates by
# reflection (WorkDatabase_Impl.<init>). AGP 9's R8 full mode strips that
# constructor despite the library's consumer rules, and the app then dies at
# startup in androidx.startup. Keep every Room database's no-arg constructor.
-keep class * extends androidx.room.RoomDatabase {
    <init>();
}

// One background AppKit observer per settings directory. No window or Dock icon.
// Build: clang -fobjc-arc -Wall -Wextra -framework AppKit -o session-themes-observer session-themes-observer.m
#import <AppKit/AppKit.h>
#import <sys/file.h>
#import <sys/stat.h>
#import <fcntl.h>
#import <unistd.h>

@interface ThemeObserver : NSObject <NSApplicationDelegate>
@property NSString *directory;
@property NSString *mode;
@property NSDate *configDate;
@property NSTask *task;
@property NSUInteger generation;
@property BOOL pending;
@end

@implementation ThemeObserver
- (void)requestUpdate {
    NSArray *names = @[NSAppearanceNameAqua, NSAppearanceNameDarkAqua];
    NSString *match = [NSApp.effectiveAppearance bestMatchFromAppearancesWithNames:names];
    self.mode = [match isEqualToString:NSAppearanceNameDarkAqua] ? @"dark" : @"light";
    NSUInteger generation = ++self.generation;
    // Let Ghostty finish applying its native appearance before our per-surface colours.
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW, 300 * NSEC_PER_MSEC), dispatch_get_main_queue(), ^{
        if (generation != self.generation) return;
        self.pending = YES;
        [self apply];
    });
}
- (void)apply {
    if (self.task || !self.pending) return;
    self.pending = NO;
    NSTask *task = [NSTask new];
    task.executableURL = [NSURL fileURLWithPath:@"/usr/bin/python3"];
    task.arguments = @[[self.directory stringByAppendingPathComponent:@"session-themes.py"], @"_broadcast", self.mode];
    task.standardInput = NSFileHandle.fileHandleWithNullDevice;
    task.standardOutput = NSFileHandle.fileHandleWithNullDevice;
    task.standardError = NSFileHandle.fileHandleWithNullDevice;
    __weak ThemeObserver *weakSelf = self;
    task.terminationHandler = ^(NSTask *finished) {
        dispatch_async(dispatch_get_main_queue(), ^{
            ThemeObserver *observer = weakSelf;
            observer.task = nil;
            if (finished.terminationStatus == 20) [NSApp terminate:nil];
            else [observer apply];
        });
    };
    NSError *error = nil;
    if (![task launchAndReturnError:&error]) {
        // No resident retry loop if Python or the installed helper is unavailable.
        [NSApp terminate:nil];
        return;
    }
    self.task = task;
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW, 10 * NSEC_PER_SEC), dispatch_get_main_queue(), ^{
        if (task.running) [task terminate];
    });
}
- (void)applicationDidFinishLaunching:(NSNotification *)notification {
    (void)notification;
    [NSApp addObserver:self forKeyPath:@"effectiveAppearance"
               options:NSKeyValueObservingOptionInitial | NSKeyValueObservingOptionNew context:NULL];
    [NSTimer scheduledTimerWithTimeInterval:2 repeats:YES block:^(NSTimer *timer) {
        (void)timer;
        NSString *path = [self.directory stringByAppendingPathComponent:@"session-themes.conf"];
        NSDate *date = [[NSFileManager.defaultManager attributesOfItemAtPath:path error:nil] fileModificationDate];
        if (!date) { [NSApp terminate:nil]; return; }
        if (![date isEqualToDate:self.configDate]) {
            self.configDate = date;
            [self requestUpdate];
        }
    }];
}
- (void)observeValueForKeyPath:(NSString *)keyPath ofObject:(id)object
                       change:(NSDictionary *)change context:(void *)context {
    (void)keyPath; (void)object; (void)change; (void)context;
    [self requestUpdate];
}
@end

int main(int argc, const char *argv[]) {
    (void)argc;
    @autoreleasepool {
        umask(0077);
        NSString *directory = [[[NSString stringWithUTF8String:argv[0]] stringByResolvingSymlinksInPath] stringByDeletingLastPathComponent];
        NSString *lockPath = [directory stringByAppendingPathComponent:@".session-themes-observer.lock"];
        int lock = open(lockPath.fileSystemRepresentation, O_CREAT | O_RDWR | O_CLOEXEC, 0600);
        if (lock < 0 || flock(lock, LOCK_EX | LOCK_NB) != 0) return 0;
        ftruncate(lock, 0);
        dprintf(lock, "%d\n", getpid());
        [NSApplication sharedApplication];
        [NSApp setActivationPolicy:NSApplicationActivationPolicyProhibited];
        ThemeObserver *observer = [ThemeObserver new];
        observer.directory = directory;
        NSApp.delegate = observer;
        [NSApp run];
        close(lock);
    }
    return 0;
}

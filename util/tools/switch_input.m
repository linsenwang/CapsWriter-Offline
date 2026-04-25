#import <Carbon/Carbon.h>
#import <Foundation/Foundation.h>
#import <stdio.h>

void printCurrentInputSource() {
    TISInputSourceRef current = TISCopyCurrentKeyboardInputSource();
    if (current) {
        NSString *sourceID = (__bridge NSString *)TISGetInputSourceProperty(current, kTISPropertyInputSourceID);
        NSString *localizedName = (__bridge NSString *)TISGetInputSourceProperty(current, kTISPropertyLocalizedName);
        printf("%s (%s)\n", [sourceID UTF8String], [localizedName UTF8String]);
        CFRelease(current);
    }
}

void listEnabledInputSources() {
    NSArray *sources = CFBridgingRelease(TISCreateInputSourceList(NULL, FALSE));
    for (id sourceObj in sources) {
        TISInputSourceRef source = (__bridge TISInputSourceRef)sourceObj;
        NSString *sourceID = (__bridge NSString *)TISGetInputSourceProperty(source, kTISPropertyInputSourceID);
        NSString *localizedName = (__bridge NSString *)TISGetInputSourceProperty(source, kTISPropertyLocalizedName);
        printf("%s (%s)\n", [sourceID UTF8String], [localizedName UTF8String]);
    }
}

BOOL selectInputSource(const char *inputSourceID) {
    NSString *targetID = [NSString stringWithUTF8String:inputSourceID];
    NSArray *sources = CFBridgingRelease(TISCreateInputSourceList(
        (__bridge CFDictionaryRef)@{
            (__bridge NSString *)kTISPropertyInputSourceID : targetID
        },
        FALSE
    ));
    
    if (sources.count == 0) {
        fprintf(stderr, "Input source not found: %s\n", inputSourceID);
        return NO;
    }
    
    TISInputSourceRef source = (__bridge TISInputSourceRef)sources[0];
    OSStatus status = TISSelectInputSource(source);
    
    if (status != noErr) {
        fprintf(stderr, "Failed to select input source: %d\n", (int)status);
        return NO;
    }
    
    return YES;
}

int main(int argc, const char * argv[]) {
    @autoreleasepool {
        if (argc < 2) {
            printf("Usage: switch_input <current|list|select <id>>\n");
            return 1;
        }
        
        NSString *command = [NSString stringWithUTF8String:argv[1]];
        
        if ([command isEqualToString:@"current"]) {
            printCurrentInputSource();
            return 0;
        } else if ([command isEqualToString:@"list"]) {
            listEnabledInputSources();
            return 0;
        } else if ([command isEqualToString:@"select"]) {
            if (argc < 3) {
                fprintf(stderr, "Usage: switch_input select <input_source_id>\n");
                return 1;
            }
            return selectInputSource(argv[2]) ? 0 : 1;
        } else {
            fprintf(stderr, "Unknown command: %s\n", argv[1]);
            return 1;
        }
    }
}

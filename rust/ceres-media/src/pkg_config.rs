//! The link inputs named by FFmpeg's pkg-config files, read by the build script and compiled
//! into the crate only for its tests.

/// One input a pkg-config `Libs` line hands the linker.
#[derive(Debug, PartialEq, Eq)]
pub enum LinkInput {
    Search(String),
    Library(String),
    Framework(String),
}

/// Appends the inputs of the `Libs` and `Libs.private` lines of `pkgconfig` to `inputs`,
/// once each and without the libraries in `skip`.
///
/// Under `--toolchain=msvc` FFmpeg rewrites `-L<dir>` as `-libpath:<dir>` and `-l<name>` as
/// `<name>.lib`, and `-libpath:` has to be read before `-l` since it starts with it.
pub fn link_inputs(pkgconfig: &str, skip: &[&str], inputs: &mut Vec<LinkInput>) {
    let mut tokens = pkgconfig
        .lines()
        .filter_map(|line| {
            line.strip_prefix("Libs:")
                .or_else(|| line.strip_prefix("Libs.private:"))
        })
        .flat_map(str::split_whitespace);
    while let Some(token) = tokens.next() {
        let input = if let Some(directory) = strip_prefix_ignore_case(token, "-libpath:")
            .or_else(|| strip_prefix_ignore_case(token, "/libpath:"))
            .or_else(|| token.strip_prefix("-L"))
        {
            // An unexpanded `${libdir}` is FFmpeg's own directory, searched already.
            if directory.contains("${") {
                continue;
            }
            LinkInput::Search(directory.to_owned())
        } else if let Some(library) = token
            .strip_prefix("-l")
            .or_else(|| strip_suffix_ignore_case(token, ".lib"))
        {
            if skip.contains(&library) {
                continue;
            }
            LinkInput::Library(library.to_owned())
        } else if token == "-framework" {
            LinkInput::Framework(tokens.next().expect("a framework name").to_owned())
        } else {
            continue;
        };
        if !inputs.contains(&input) {
            inputs.push(input);
        }
    }
}

fn strip_prefix_ignore_case<'a>(token: &'a str, prefix: &str) -> Option<&'a str> {
    let head = token.get(..prefix.len())?;
    head.eq_ignore_ascii_case(prefix)
        .then(|| &token[prefix.len()..])
}

fn strip_suffix_ignore_case<'a>(token: &'a str, suffix: &str) -> Option<&'a str> {
    let start = token.len().checked_sub(suffix.len())?;
    let tail = token.get(start..)?;
    tail.eq_ignore_ascii_case(suffix).then(|| &token[..start])
}

#[cfg(test)]
mod tests {
    use super::LinkInput::{Framework, Library, Search};
    use super::*;

    fn read(pkgconfig: &str) -> Vec<LinkInput> {
        let mut inputs = Vec::new();
        link_inputs(pkgconfig, &["avcodec", "avutil", "openh264"], &mut inputs);
        inputs
    }

    #[test]
    fn reads_an_msvc_libs_line() {
        let pkgconfig = "Name: libavcodec\n\
            Libs: -L${libdir} -lavcodec -libpath:C:/abc/lib openh264.lib ole32.lib User32.LIB\n\
            Cflags: -I${includedir}\n";
        assert_eq!(
            read(pkgconfig),
            [
                Search("C:/abc/lib".into()),
                Library("ole32".into()),
                Library("User32".into()),
            ]
        );
    }

    #[test]
    fn reads_every_spelling_of_a_search_path() {
        assert_eq!(
            read("Libs: /LIBPATH:C:/abc -LIBPATH:C:/abcd -L/abc"),
            [
                Search("C:/abc".into()),
                Search("C:/abcd".into()),
                Search("/abc".into()),
            ]
        );
    }

    #[test]
    fn reads_a_unix_libs_private_line() {
        let pkgconfig = "Libs: -L${libdir} -lavcodec\n\
            Libs.private: -lm -framework CoreFoundation -pthread -lm -lopenh264 -lc++\n";
        assert_eq!(
            read(pkgconfig),
            [
                Library("m".into()),
                Framework("CoreFoundation".into()),
                Library("c++".into()),
            ]
        );
    }
}

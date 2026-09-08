import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Enumeration;
import java.util.jar.JarEntry;
import java.util.jar.JarFile;
import java.util.jar.JarOutputStream;
import jdk.internal.org.objectweb.asm.ClassReader;
import jdk.internal.org.objectweb.asm.ClassWriter;
import jdk.internal.org.objectweb.asm.Opcodes;
import jdk.internal.org.objectweb.asm.tree.AbstractInsnNode;
import jdk.internal.org.objectweb.asm.tree.ClassNode;
import jdk.internal.org.objectweb.asm.tree.InsnList;
import jdk.internal.org.objectweb.asm.tree.InsnNode;
import jdk.internal.org.objectweb.asm.tree.MethodInsnNode;
import jdk.internal.org.objectweb.asm.tree.MethodNode;

/**
 * Tiny WebRTC playout hook.
 *
 * It does NOT touch PCM buffers. It only registers/unregisters WebRTC's android.media.AudioTrack
 * around play()/stop(), so the Signal-side controller can update gain when the user changes it.
 */
public final class PatchWebRtcAudioTrack {
  private static final String TARGET_CLASS = "org/webrtc/audio/WebRtcAudioTrack";
  private static final String AUDIO_TRACK = "android/media/AudioTrack";
  private static final String BRIDGE = "org/thoughtcrime/securesms/webrtc/audio/HqCallGainBridge";

  private static int registerCalls = 0;
  private static int unregisterCalls = 0;

  private PatchWebRtcAudioTrack() {}

  public static void main(String[] args) throws Exception {
    if (args.length != 2) {
      throw new IllegalArgumentException("usage: PatchWebRtcAudioTrack <input.jar> <output.jar>");
    }

    Path input = Path.of(args[0]);
    Path output = Path.of(args[1]);

    try (JarFile jar = new JarFile(input.toFile());
         JarOutputStream out = new JarOutputStream(Files.newOutputStream(output))) {
      Enumeration<JarEntry> entries = jar.entries();
      while (entries.hasMoreElements()) {
        JarEntry entry = entries.nextElement();
        String name = entry.getName();

        if (name.startsWith("META-INF/") &&
            (name.endsWith(".SF") || name.endsWith(".RSA") || name.endsWith(".DSA") || name.endsWith(".EC"))) {
          continue;
        }

        JarEntry replacement = new JarEntry(name);
        replacement.setTime(entry.getTime());
        out.putNextEntry(replacement);

        if (!entry.isDirectory()) {
          byte[] bytes;
          try (InputStream in = jar.getInputStream(entry)) {
            bytes = readAll(in);
          }
          if (name.equals(TARGET_CLASS + ".class")) {
            bytes = transform(bytes);
          }
          out.write(bytes);
        }
        out.closeEntry();
      }
    }

    System.out.println("REGISTER_CALLS=" + registerCalls);
    System.out.println("UNREGISTER_CALLS=" + unregisterCalls);
  }

  private static byte[] transform(byte[] bytes) {
    ClassReader reader = new ClassReader(bytes);
    ClassNode clazz = new ClassNode();
    reader.accept(clazz, 0);

    if (!TARGET_CLASS.equals(clazz.name)) {
      return bytes;
    }

    boolean changed = false;
    for (MethodNode method : clazz.methods) {
      for (AbstractInsnNode current = method.instructions.getFirst(); current != null; ) {
        AbstractInsnNode next = current.getNext();
        if (current instanceof MethodInsnNode call &&
            call.getOpcode() == Opcodes.INVOKEVIRTUAL &&
            AUDIO_TRACK.equals(call.owner) &&
            "()V".equals(call.desc) &&
            ("play".equals(call.name) || "stop".equals(call.name))) {
          String bridgeMethod = "play".equals(call.name) ? "registerAudioTrack" : "unregisterAudioTrack";
          InsnList hook = new InsnList();
          // Stack before play()/stop(): [AudioTrack]. DUP preserves the receiver for the original call.
          hook.add(new InsnNode(Opcodes.DUP));
          hook.add(new MethodInsnNode(
              Opcodes.INVOKESTATIC,
              BRIDGE,
              bridgeMethod,
              "(Landroid/media/AudioTrack;)V",
              false));
          method.instructions.insertBefore(call, hook);

          if ("play".equals(call.name)) {
            registerCalls++;
          } else {
            unregisterCalls++;
          }
          changed = true;
        }
        current = next;
      }
    }

    if (!changed) {
      return bytes;
    }

    ClassWriter writer = new ClassWriter(reader, ClassWriter.COMPUTE_MAXS);
    clazz.accept(writer);
    return writer.toByteArray();
  }

  private static byte[] readAll(InputStream in) throws IOException {
    ByteArrayOutputStream out = new ByteArrayOutputStream();
    in.transferTo(out);
    return out.toByteArray();
  }
}

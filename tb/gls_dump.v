// Optional VCD dump for gate-level power analysis: enabled with +dump.
`timescale 1ns/1ps
module gls_dump;
    initial begin
        if ($test$plusargs("dump")) begin
            $dumpfile("gls.vcd");
            $dumpvars(0, sa_top);
        end
    end
endmodule
